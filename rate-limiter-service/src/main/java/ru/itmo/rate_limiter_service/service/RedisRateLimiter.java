package ru.itmo.rate_limiter_service.service;

import java.time.Instant;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Service;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;
import ru.itmo.rate_limiter_service.metrics.RateLimiterMetrics;
import ru.itmo.rate_limiter_service.model.Algorithm;
import ru.itmo.rate_limiter_service.model.RateLimiterConfig;

@Service
@RequiredArgsConstructor
public class RedisRateLimiter implements RateLimiter {
	private static final Logger log = LoggerFactory.getLogger(RedisRateLimiter.class);

	private static final RedisScript<Long> FIXED_WINDOW_SCRIPT = new DefaultRedisScript<>("""
		local current = redis.call('INCR', KEYS[1])
		if current == 1 then
		  redis.call('EXPIRE', KEYS[1], ARGV[1])
		end
		return current
		""", Long.class);

	private static final RedisScript<Number> SLIDING_WINDOW_SCRIPT = new DefaultRedisScript<>("""
		local current = redis.call('INCR', KEYS[1])
		if current == 1 then
		  redis.call('PEXPIRE', KEYS[1], ARGV[1])
		end
		local previous = tonumber(redis.call('GET', KEYS[2]) or "0")
		local elapsed = tonumber(ARGV[2])
		local windowMs = tonumber(ARGV[3])
		local weight = (windowMs - elapsed) / windowMs
		if weight < 0 then
		  weight = 0
		end
		return previous * weight + current
		""", Number.class);

	private static final RedisScript<Long> TOKEN_BUCKET_SCRIPT = new DefaultRedisScript<>("""
		local capacity = tonumber(ARGV[1])
		local fillRate = tonumber(ARGV[2])
		local nowMs = tonumber(ARGV[3])
		local ttlMs = tonumber(ARGV[4])

		local data = redis.call('HMGET', KEYS[1], 'tokens', 'lastRefill')
		local tokens = tonumber(data[1])
		local lastRefill = tonumber(data[2])
		if tokens == nil then
		  tokens = capacity
		  lastRefill = nowMs
		end

		local delta = nowMs - lastRefill
		if delta < 0 then
		  delta = 0
		end
		local refill = (delta / 1000.0) * fillRate
		tokens = math.min(capacity, tokens + refill)

		local allowed = 0
		if tokens >= 1 then
		  tokens = tokens - 1
		  allowed = 1
		end

		redis.call('HMSET', KEYS[1], 'tokens', tokens, 'lastRefill', nowMs)
		redis.call('PEXPIRE', KEYS[1], ttlMs)
		return allowed
		""", Long.class);

	private final StringRedisTemplate redisTemplate;
	private final RedisAvailability redisAvailability;
	private final RateLimiterMetrics metrics;
	private final RateLimiterProperties properties;

	@Override
	public boolean allow(RateLimiterConfig config) {
		if (!redisAvailability.isAvailable()) {
			return properties.isFailOpen();
		}

		boolean allowed;
		var timerSample = metrics.startRedisTimer();
		try {
			allowed = switch (config.getAlgorithm()) {
				case FIXED -> allowFixed(config);
				case SLIDING -> allowSliding(config);
				case TOKEN -> allowToken(config);
			};
			redisAvailability.markAvailable();
		} catch (Exception ex) {
			metrics.incrementRedisError();
			redisAvailability.markUnavailable(ex.getMessage());
			log.warn("Redis request failed, applying fail-open policy: {}", ex.getMessage());
			return properties.isFailOpen();
		} finally {
			metrics.stopRedisTimer(timerSample);
		}
		return allowed;
	}

	private boolean allowFixed(RateLimiterConfig config) {
		long windowSeconds = config.getWindowSeconds();
		long now = Instant.now().getEpochSecond();
		long windowId = now / windowSeconds;
		String key = "ratelimiter:fixed:" + windowId;
		Long count = redisTemplate.execute(
			FIXED_WINDOW_SCRIPT,
			List.of(key),
			String.valueOf(windowSeconds));
		return count != null && count <= config.getLimit();
	}

	private boolean allowSliding(RateLimiterConfig config) {
		long windowSeconds = config.getWindowSeconds();
		long nowMs = System.currentTimeMillis();
		long windowMs = windowSeconds * 1000L;
		long currentWindowStart = nowMs - (nowMs % windowMs);
		long previousWindowStart = currentWindowStart - windowMs;
		long elapsed = nowMs - currentWindowStart;
		long ttlMs = windowMs * 2;

		String currentKey = "ratelimiter:sliding:" + currentWindowStart;
		String previousKey = "ratelimiter:sliding:" + previousWindowStart;

		Number estimate = redisTemplate.execute(
			SLIDING_WINDOW_SCRIPT,
			List.of(currentKey, previousKey),
			String.valueOf(ttlMs),
			String.valueOf(elapsed),
			String.valueOf(windowMs));
		return estimate != null && estimate.doubleValue() <= config.getLimit();
	}

	private boolean allowToken(RateLimiterConfig config) {
		long capacity = config.getCapacity();
		double fillRate = config.getFillRate();
		long nowMs = System.currentTimeMillis();
		long ttlMs = computeTokenTtlMs(capacity, fillRate);

		Long allowed = redisTemplate.execute(
			TOKEN_BUCKET_SCRIPT,
			List.of("ratelimiter:token"),
			String.valueOf(capacity),
			String.valueOf(fillRate),
			String.valueOf(nowMs),
			String.valueOf(ttlMs));
		return allowed != null && allowed == 1L;
	}

	private long computeTokenTtlMs(long capacity, double fillRate) {
		if (fillRate <= 0) {
			return 1000;
		}
		double refillSeconds = capacity / fillRate;
		long ttl = (long) Math.ceil(refillSeconds * 2000);
		return Math.max(1000, ttl);
	}
}
