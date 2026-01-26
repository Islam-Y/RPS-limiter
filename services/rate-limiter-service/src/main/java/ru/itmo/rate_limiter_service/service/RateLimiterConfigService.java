package ru.itmo.rate_limiter_service.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicReference;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.data.redis.core.StringRedisTemplate;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;
import ru.itmo.rate_limiter_service.model.Algorithm;
import ru.itmo.rate_limiter_service.model.RateLimiterConfig;
import ru.itmo.rate_limiter_service.model.RateLimiterConfigPayload;

@Service
@RequiredArgsConstructor
public class RateLimiterConfigService {
	private static final Logger log = LoggerFactory.getLogger(RateLimiterConfigService.class);
	private static final int REDIS_SCAN_BATCH_SIZE = 500;
	private static final String FIXED_KEY_PATTERN = "ratelimiter:fixed:*";
	private static final String SLIDING_KEY_PATTERN = "ratelimiter:sliding:*";
	private static final String TOKEN_KEY = "ratelimiter:token";

	private final RateLimiterProperties properties;
	private final StringRedisTemplate redisTemplate;
	private final ObjectMapper objectMapper;
	private final AtomicReference<RateLimiterConfig> current = new AtomicReference<>();

	@PostConstruct
	public void init() {
		current.set(defaultConfig());
		loadFromRedis();
	}

	@Scheduled(fixedDelayString = "${ratelimiter.config-refresh-interval:30s}")
	public void refreshFromRedis() {
		if (!properties.isLoadConfigFromRedis()) {
			return;
		}
		try {
			RateLimiterConfig base = current.get();
			RateLimiterConfig loaded = loadConfigFromRedis(base);
			if (loaded == null || isSameConfig(base, loaded)) {
				return;
			}
			if (base.getAlgorithm() != loaded.getAlgorithm()) {
				resetRedisState();
				log.info("Switched rate-limiting algorithm from {} to {} (source=redis)",
					base.getAlgorithm(), loaded.getAlgorithm());
			}
			current.set(loaded);
			log.info("Refreshed rate limiter config from Redis: algorithm={}, limit={}, window={}, capacity={}, fillRate={}",
				loaded.getAlgorithm(), loaded.getLimit(), loaded.getWindowSeconds(),
				loaded.getCapacity(), loaded.getFillRate());
		} catch (Exception ex) {
			log.warn("Failed to refresh config from Redis: {}", ex.getMessage());
		}
	}

	private void loadFromRedis() {
		if (!properties.isLoadConfigFromRedis()) {
			return;
		}
		try {
			RateLimiterConfig loaded = loadConfigFromRedis(current.get());
			if (loaded == null) {
				return;
			}
			current.set(loaded);
			log.info("Loaded rate limiter config from Redis: algorithm={}, limit={}, window={}, capacity={}, fillRate={}",
				loaded.getAlgorithm(), loaded.getLimit(), loaded.getWindowSeconds(),
				loaded.getCapacity(), loaded.getFillRate());
		} catch (Exception ex) {
			log.warn("Failed to load config from Redis, using defaults: {}", ex.getMessage());
		}
	}

	public RateLimiterConfig getCurrent() {
		return current.get();
	}

	public RateLimiterConfig applyConfig(RateLimiterConfigPayload payload, String source, boolean requireAllFields) {
		Objects.requireNonNull(payload, "payload");
		RateLimiterConfig base = current.get();
		RateLimiterConfig updated = resolveConfig(payload, base, requireAllFields);
		if (base.getAlgorithm() != updated.getAlgorithm()) {
			resetRedisState();
			log.info("Switched rate-limiting algorithm from {} to {} (source={})",
				base.getAlgorithm(), updated.getAlgorithm(), source);
		}
		persistConfig(updated);
		current.set(updated);
		log.info("Applied rate limiter config (source={}): algorithm={}, limit={}, window={}, capacity={}, fillRate={}",
			source, updated.getAlgorithm(), updated.getLimit(), updated.getWindowSeconds(),
			updated.getCapacity(), updated.getFillRate());
		return updated;
	}

	public RateLimiterConfig applyAlgorithm(Algorithm algorithm) {
		RateLimiterConfigPayload payload = new RateLimiterConfigPayload();
		payload.setAlgorithm(algorithm);
		return applyConfig(payload, "api", false);
	}

	private RateLimiterConfig resolveConfig(RateLimiterConfigPayload payload, RateLimiterConfig base, boolean requireAllFields) {
		Algorithm algorithm = payload.getAlgorithm() != null ? payload.getAlgorithm() : base.getAlgorithm();
		if (algorithm == null) {
			throw new IllegalArgumentException("Algorithm is required");
		}

		if (requireAllFields) {
			if ((algorithm == Algorithm.FIXED || algorithm == Algorithm.SLIDING)
				&& (payload.getLimit() == null || payload.getWindow() == null)) {
				throw new IllegalArgumentException("limit and window are required for fixed/sliding algorithms");
			}
			if (algorithm == Algorithm.TOKEN
				&& (payload.getCapacity() == null || payload.getFillRate() == null)) {
				throw new IllegalArgumentException("capacity and fillRate are required for token algorithm");
			}
		}

		long limit = payload.getLimit() != null ? payload.getLimit() : base.getLimit();
		long window = payload.getWindow() != null ? payload.getWindow() : base.getWindowSeconds();
		long capacity = payload.getCapacity() != null ? payload.getCapacity() : base.getCapacity();
		double fillRate = payload.getFillRate() != null ? payload.getFillRate() : base.getFillRate();

		RateLimiterConfig resolved = new RateLimiterConfig(algorithm, limit, window, capacity, fillRate);
		return validateAndClamp(resolved);
	}

	private RateLimiterConfig validateAndClamp(RateLimiterConfig candidate) {
		RateLimiterProperties.Bounds bounds = properties.getBounds();
		long limit = clampLong(candidate.getLimit(), bounds.getMinLimit(), bounds.getMaxLimit(), "limit");
		long window = clampLong(candidate.getWindowSeconds(), bounds.getMinWindowSeconds(), bounds.getMaxWindowSeconds(), "window");
		long capacity = clampLong(candidate.getCapacity(), bounds.getMinCapacity(), bounds.getMaxCapacity(), "capacity");
		double fillRate = clampDouble(candidate.getFillRate(), bounds.getMinFillRate(), bounds.getMaxFillRate(), "fillRate");
		return new RateLimiterConfig(candidate.getAlgorithm(), limit, window, capacity, fillRate);
	}

	private long clampLong(long value, long min, long max, String name) {
		if (value < min) {
			throw new IllegalArgumentException(name + " must be >= " + min);
		}
		if (max > 0 && value > max) {
			log.warn("{} capped from {} to {}", name, value, max);
			return max;
		}
		return value;
	}

	private double clampDouble(double value, double min, double max, String name) {
		if (value < min) {
			throw new IllegalArgumentException(name + " must be >= " + min);
		}
		if (max > 0 && value > max) {
			log.warn("{} capped from {} to {}", name, value, max);
			return max;
		}
		return value;
	}

	private void persistConfig(RateLimiterConfig config) {
		if (!properties.isStoreConfigInRedis()) {
			return;
		}
		try {
			String json = objectMapper.writeValueAsString(config.toPayload());
			redisTemplate.opsForValue().set(properties.getConfigKey(), json);
		} catch (Exception ex) {
			log.warn("Failed to persist config in Redis: {}", ex.getMessage());
		}
	}

	private RateLimiterConfig loadConfigFromRedis(RateLimiterConfig base) throws Exception {
		String json = redisTemplate.opsForValue().get(properties.getConfigKey());
		if (!StringUtils.hasText(json)) {
			return null;
		}
		RateLimiterConfigPayload payload = objectMapper.readValue(json, RateLimiterConfigPayload.class);
		return resolveConfig(payload, base, false);
	}

	private boolean isSameConfig(RateLimiterConfig first, RateLimiterConfig second) {
		if (first == second) {
			return true;
		}
		return first.getAlgorithm() == second.getAlgorithm()
			&& first.getLimit() == second.getLimit()
			&& first.getWindowSeconds() == second.getWindowSeconds()
			&& first.getCapacity() == second.getCapacity()
			&& Double.compare(first.getFillRate(), second.getFillRate()) == 0;
	}

	private RateLimiterConfig defaultConfig() {
		return new RateLimiterConfig(
			properties.getAlgorithm(),
			properties.getLimit(),
			properties.getWindowSeconds(),
			properties.getCapacity(),
			properties.getFillRate());
	}

	private void resetRedisState() {
		try {
			deleteByPattern(FIXED_KEY_PATTERN);
			deleteByPattern(SLIDING_KEY_PATTERN);
			redisTemplate.delete(TOKEN_KEY);
		} catch (Exception ex) {
			log.warn("Failed to reset Redis state after algorithm switch: {}", ex.getMessage());
		}
	}

	private void deleteByPattern(String pattern) {
		redisTemplate.execute((RedisCallback<Void>) connection -> {
			ScanOptions options = ScanOptions.scanOptions()
				.match(pattern)
				.count(REDIS_SCAN_BATCH_SIZE)
				.build();
			List<byte[]> batch = new ArrayList<>(REDIS_SCAN_BATCH_SIZE);
			try (Cursor<byte[]> cursor = connection.scan(options)) {
				while (cursor.hasNext()) {
					batch.add(cursor.next());
					if (batch.size() >= REDIS_SCAN_BATCH_SIZE) {
						connection.del(batch.toArray(new byte[0][]));
						batch.clear();
					}
				}
			}
			if (!batch.isEmpty()) {
				connection.del(batch.toArray(new byte[0][]));
			}
			return null;
		});
	}
}
