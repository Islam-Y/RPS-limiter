package ru.itmo.rate_limiter_service.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class AdaptiveConfigRequest {
	private long timestamp;
	private double observedRps;
	private double allowedRps;
	private double rejectedRps;
	private double rejectedRate;
	private double peakRps1s;
	private double burstRatio;
	private double coefficientOfVariation;
	private double latencyP95;
	private long errors5xx;
	private boolean applyRecommendations;
	@JsonProperty("currentConfig")
	private RateLimiterConfigPayload currentConfig;
}
