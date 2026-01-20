package ru.itmo.rate_limiter_service.service;

import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class RedisAvailability {
	private static final Logger log = LoggerFactory.getLogger(RedisAvailability.class);

	private final AtomicBoolean available = new AtomicBoolean(true);

	public boolean isAvailable() {
		return available.get();
	}

	public void markUnavailable(String reason) {
		if (available.compareAndSet(true, false)) {
			log.warn("Redis connection lost, entering fail-open mode: {}", reason);
		}
	}

	public void markAvailable() {
		if (available.compareAndSet(false, true)) {
			log.info("Redis reconnected, resuming normal operation");
		}
	}
}
