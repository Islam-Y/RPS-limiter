package ru.itmo.rate_limiter_service.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicReference;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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

	private final RateLimiterProperties properties;
	private final StringRedisTemplate redisTemplate;
	private final ObjectMapper objectMapper;
	private final AtomicReference<RateLimiterConfig> current = new AtomicReference<>();

	@PostConstruct
	public void init() {
		current.set(defaultConfig());
		loadFromRedis();
	}

	private void loadFromRedis() {
		if (!properties.isLoadConfigFromRedis()) {
			return;
		}
		try {
			String json = redisTemplate.opsForValue().get(properties.getConfigKey());
			if (!StringUtils.hasText(json)) {
				return;
			}
			RateLimiterConfigPayload payload = objectMapper.readValue(json, RateLimiterConfigPayload.class);
			RateLimiterConfig loaded = resolveConfig(payload, current.get(), false);
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
		RateLimiterConfig updated = resolveConfig(payload, current.get(), requireAllFields);
		RateLimiterConfig previous = current.getAndSet(updated);
		persistConfig(updated);
		if (previous.getAlgorithm() != updated.getAlgorithm()) {
			log.info("Switched rate-limiting algorithm from {} to {} (source={})",
				previous.getAlgorithm(), updated.getAlgorithm(), source);
		}
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

	private RateLimiterConfig defaultConfig() {
		return new RateLimiterConfig(
			properties.getAlgorithm(),
			properties.getLimit(),
			properties.getWindowSeconds(),
			properties.getCapacity(),
			properties.getFillRate());
	}
}
