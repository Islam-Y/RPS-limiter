package ru.itmo.rate_limiter_service.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import lombok.RequiredArgsConstructor;
import ru.itmo.rate_limiter_service.model.Algorithm;
import ru.itmo.rate_limiter_service.model.RateLimiterConfig;
import ru.itmo.rate_limiter_service.model.RateLimiterConfigPayload;
import ru.itmo.rate_limiter_service.service.RateLimiterConfigService;

@RestController
@RequestMapping("/config")
@RequiredArgsConstructor
public class ConfigController {
	private final RateLimiterConfigService configService;

	@PostMapping("/limits")
	public RateLimiterConfigPayload updateLimits(@RequestBody RateLimiterConfigPayload payload) {
		RateLimiterConfig config = configService.applyConfig(payload, "api", true);
		return config.toPayload();
	}

	@GetMapping("/limits")
	public RateLimiterConfigPayload getLimits() {
		return configService.getCurrent().toPayload();
	}

	@PostMapping("/algorithm")
	public RateLimiterConfigPayload updateAlgorithm(
		@RequestBody(required = false) RateLimiterConfigPayload payload,
		@RequestParam(required = false) Algorithm algorithm) {
		Algorithm selected = algorithm != null ? algorithm : payload != null ? payload.getAlgorithm() : null;
		if (selected == null) {
			throw new IllegalArgumentException("algorithm is required");
		}
		return configService.applyAlgorithm(selected).toPayload();
	}
}
