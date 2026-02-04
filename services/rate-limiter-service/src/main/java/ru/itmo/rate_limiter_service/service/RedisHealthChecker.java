package ru.itmo.rate_limiter_service.service;

import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import ru.itmo.rate_limiter_service.metrics.RateLimiterMetrics;
import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class RedisHealthChecker {
	private final StringRedisTemplate redisTemplate;
	private final RedisConnectionFactory redisConnectionFactory;
	private final RedisAvailability redisAvailability;
	private final RateLimiterMetrics metrics;

	@Scheduled(fixedDelayString = "${ratelimiter.redis-health-interval:5s}")
	public void checkRedis() {
		try {
			String pong = redisTemplate.execute((RedisCallback<String>) connection -> connection.ping());
			if (pong != null) {
				redisAvailability.markAvailable();
			} else {
				metrics.incrementRedisError();
				redisAvailability.markUnavailable("Empty PING response");
				resetConnection();
			}
		} catch (Exception ex) {
			metrics.incrementRedisError();
			redisAvailability.markUnavailable(ex.getMessage());
			resetConnection();
		}
	}

	private void resetConnection() {
		if (redisConnectionFactory instanceof LettuceConnectionFactory lettuce) {
			lettuce.resetConnection();
		}
	}
}
