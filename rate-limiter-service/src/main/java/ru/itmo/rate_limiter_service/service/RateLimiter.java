package ru.itmo.rate_limiter_service.service;

import ru.itmo.rate_limiter_service.model.RateLimiterConfig;

public interface RateLimiter {
	boolean allow(RateLimiterConfig config);
}
