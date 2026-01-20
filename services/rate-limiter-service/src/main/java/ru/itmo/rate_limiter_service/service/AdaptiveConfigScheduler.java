package ru.itmo.rate_limiter_service.service;

import java.time.Duration;
import java.time.Instant;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;
import ru.itmo.rate_limiter_service.metrics.RateLimiterMetrics;
import ru.itmo.rate_limiter_service.metrics.TrafficStats;
import ru.itmo.rate_limiter_service.model.AdaptiveConfigRequest;
import ru.itmo.rate_limiter_service.model.RateLimiterConfig;
import ru.itmo.rate_limiter_service.model.RateLimiterConfigPayload;

@Component
@RequiredArgsConstructor
public class AdaptiveConfigScheduler {
	private static final Logger log = LoggerFactory.getLogger(AdaptiveConfigScheduler.class);

	private final RateLimiterProperties properties;
	private final RateLimiterConfigService configService;
	private final TrafficStats trafficStats;
	private final RateLimiterMetrics metrics;
	private final RestTemplate restTemplate;

	@Scheduled(fixedDelayString = "${ratelimiter.adaptive.interval:30s}")
	public void updateFromAdaptiveModule() {
		if (!properties.getAdaptive().isEnabled()) {
			return;
		}
		String url = properties.getAdaptive().getUrl();
		if (!StringUtils.hasText(url)) {
			log.warn("Adaptive mode enabled but adaptive.url is empty");
			return;
		}

		Duration interval = properties.getAdaptive().getInterval();
		var snapshot = trafficStats.snapshotAndReset(interval);
		RateLimiterConfig config = configService.getCurrent();

		AdaptiveConfigRequest request = new AdaptiveConfigRequest();
		request.setTimestamp(Instant.now().toEpochMilli());
		request.setObservedRps(snapshot.observedRps());
		request.setRejectedRate(snapshot.rejectedRate());
		request.setErrors5xx(snapshot.errors5xx());
		request.setLatencyP95(metrics.getRequestLatencyP95());
		request.setAlgorithm(config.getAlgorithm());
		request.setLimit(config.getLimit());
		request.setWindow(config.getWindowSeconds());
		request.setCapacity(config.getCapacity());
		request.setFillRate(config.getFillRate());

		log.info("AI request sent (interval {} ms) to {}", interval.toMillis(), url);

		try {
			RateLimiterConfigPayload response =
				restTemplate.postForObject(url, request, RateLimiterConfigPayload.class);
			if (response == null) {
				log.warn("AI module returned empty response");
				return;
			}
			configService.applyConfig(response, "adaptive", true);
		} catch (RestClientException ex) {
			log.warn("AI module unreachable, continuing with last limits: {}", ex.getMessage());
		} catch (IllegalArgumentException ex) {
			log.warn("AI module provided invalid config: {}", ex.getMessage());
		}
	}
}
