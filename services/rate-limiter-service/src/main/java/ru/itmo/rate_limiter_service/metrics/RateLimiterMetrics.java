package ru.itmo.rate_limiter_service.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.distribution.HistogramSnapshot;
import io.micrometer.core.instrument.distribution.ValueAtPercentile;
import jakarta.annotation.PostConstruct;
import java.time.Duration;
import java.util.EnumMap;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import ru.itmo.rate_limiter_service.model.Algorithm;
import ru.itmo.rate_limiter_service.service.RateLimiterConfigService;
import ru.itmo.rate_limiter_service.service.RedisAvailability;

@Component
@RequiredArgsConstructor
public class RateLimiterMetrics {
	private final MeterRegistry registry;
	private final RateLimiterConfigService configService;
	private final RedisAvailability redisAvailability;

	private Counter forwarded;
	private Counter rejected;
	private Map<Algorithm, Counter> byAlgorithm;
	private Timer requestTimer;
	private Timer redisTimer;
	private Counter redisErrors;

	@PostConstruct
	public void init() {
		this.forwarded = Counter.builder("ratelimiter_requests_total")
			.tag("decision", "forwarded")
			.register(registry);
		this.rejected = Counter.builder("ratelimiter_requests_total")
			.tag("decision", "rejected")
			.register(registry);

		this.byAlgorithm = new EnumMap<>(Algorithm.class);
		for (Algorithm algorithm : Algorithm.values()) {
			byAlgorithm.put(algorithm, Counter.builder("ratelimiter_requests_by_algorithm_total")
				.tag("algorithm", algorithm.toJson())
				.register(registry));
		}

		this.requestTimer = Timer.builder("ratelimiter_request_duration_seconds")
			.publishPercentileHistogram(true)
			.distributionStatisticExpiry(Duration.ofMinutes(5))
			.register(registry);
		this.redisTimer = Timer.builder("ratelimiter_redis_request_duration_seconds")
			.publishPercentileHistogram(true)
			.distributionStatisticExpiry(Duration.ofMinutes(5))
			.register(registry);
		this.redisErrors = Counter.builder("ratelimiter_redis_errors_total")
			.register(registry);

		Gauge.builder("ratelimiter_current_limit", () -> configService.getCurrent().getLimit())
			.register(registry);
		Gauge.builder("ratelimiter_window_seconds", () -> configService.getCurrent().getWindowSeconds())
			.register(registry);
		Gauge.builder("ratelimiter_bucket_capacity", () -> configService.getCurrent().getCapacity())
			.register(registry);
		Gauge.builder("ratelimiter_token_fill_rate", () -> configService.getCurrent().getFillRate())
			.register(registry);

		Gauge.builder("ratelimiter_redis_connected", () -> redisAvailability.isAvailable() ? 1 : 0)
			.register(registry);
		Gauge.builder("ratelimiter_mode", () -> redisAvailability.isAvailable() ? 0 : 1)
			.tag("type", "failopen")
			.register(registry);
	}

	public Timer.Sample startRequestTimer() {
		return Timer.start();
	}

	public void stopRequestTimer(Timer.Sample sample) {
		sample.stop(requestTimer);
	}

	public Timer.Sample startRedisTimer() {
		return Timer.start();
	}

	public void stopRedisTimer(Timer.Sample sample) {
		sample.stop(redisTimer);
	}

	public void incrementDecision(Algorithm algorithm, boolean allowed) {
		if (allowed) {
			forwarded.increment();
		} else {
			rejected.increment();
		}
		Counter counter = byAlgorithm.get(algorithm);
		if (counter != null) {
			counter.increment();
		}
	}

	public void incrementRedisError() {
		redisErrors.increment();
	}

	public double getRequestLatencyP95() {
		HistogramSnapshot snapshot = requestTimer.takeSnapshot();
		for (ValueAtPercentile percentile : snapshot.percentileValues()) {
			if (percentile.percentile() == 0.95) {
				return percentile.value();
			}
		}
		return snapshot.max();
	}
}
