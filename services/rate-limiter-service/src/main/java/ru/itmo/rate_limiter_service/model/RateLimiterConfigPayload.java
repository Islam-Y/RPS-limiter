package ru.itmo.rate_limiter_service.model;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class RateLimiterConfigPayload {
	private Algorithm algorithm;
	private Long limit;
	@JsonProperty("window")
	private Long window;
	@JsonAlias("burst")
	private Long capacity;
	private Double fillRate;
}
