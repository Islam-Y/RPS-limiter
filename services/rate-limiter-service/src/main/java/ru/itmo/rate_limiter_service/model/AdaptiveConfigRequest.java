package ru.itmo.rate_limiter_service.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class AdaptiveConfigRequest {
	private long timestamp;
	private double observedRps;
	private double rejectedRate;
	private double latencyP95;
	private long errors5xx;
	@JsonProperty("currentConfig")
	private RateLimiterConfigPayload currentConfig;
}
