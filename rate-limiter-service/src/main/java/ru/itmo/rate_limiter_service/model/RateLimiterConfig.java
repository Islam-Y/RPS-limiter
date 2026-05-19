package ru.itmo.rate_limiter_service.model;

import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class RateLimiterConfig {
	private final Algorithm algorithm;
	private final long limit;
	private final long windowSeconds;
	private final long capacity;
	private final double fillRate;

	@JsonIgnore
	public RateLimiterConfigPayload toPayload() {
		RateLimiterConfigPayload payload = new RateLimiterConfigPayload();
		payload.setAlgorithm(algorithm);
		payload.setLimit(limit);
		payload.setWindow(windowSeconds);
		payload.setCapacity(capacity);
		payload.setFillRate(fillRate);
		return payload;
	}
}
