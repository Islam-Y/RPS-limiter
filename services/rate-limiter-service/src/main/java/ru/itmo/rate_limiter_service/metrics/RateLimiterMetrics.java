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
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;
import ru.itmo.rate_limiter_service.model.Algorithm;
import ru.itmo.rate_limiter_service.model.RateLimiterConfigPayload;
import ru.itmo.rate_limiter_service.service.RateLimiterConfigService;
import ru.itmo.rate_limiter_service.service.RedisAvailability;

@Component
@RequiredArgsConstructor
public class RateLimiterMetrics {
	private final MeterRegistry registry;
	private final RateLimiterProperties properties;
	private final RateLimiterConfigService configService;
	private final RedisAvailability redisAvailability;

	private Counter forwarded;
	private Counter rejected;
	private Counter adaptiveApplied;
	private Counter adaptiveShadow;
	private Map<String, Counter> adaptiveByAlgorithm;
	private Map<Algorithm, Counter> byAlgorithm;
	private Timer requestTimer;
	private Timer redisTimer;
	private Counter redisErrors;
	private final AtomicReference<Algorithm> adaptiveRecommendedAlgorithm = new AtomicReference<>(Algorithm.FIXED);
	private final AtomicLong adaptiveRecommendedLimit = new AtomicLong();
	private final AtomicLong adaptiveRecommendedWindowSeconds = new AtomicLong();
	private final AtomicLong adaptiveRecommendedCapacity = new AtomicLong();
	private final AtomicReference<Double> adaptiveRecommendedFillRate = new AtomicReference<>(0.0);

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
		this.adaptiveApplied = Counter.builder("ratelimiter_adaptive_recommendations_total")
			.tag("mode", "applied")
			.register(registry);
		this.adaptiveShadow = Counter.builder("ratelimiter_adaptive_recommendations_total")
			.tag("mode", "shadow")
			.register(registry);
		this.adaptiveByAlgorithm = new java.util.HashMap<>();
		for (String mode : new String[] { "applied", "shadow" }) {
			for (Algorithm algorithm : Algorithm.values()) {
				adaptiveByAlgorithm.put(
					mode + ":" + algorithm.name(),
					Counter.builder("ratelimiter_adaptive_recommendations_by_algorithm_total")
						.tag("mode", mode)
						.tag("algorithm", algorithm.toJson())
						.register(registry)
				);
			}
		}

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
		Gauge.builder("ratelimiter_adaptive_apply_enabled", () -> properties.getAdaptive().isApplyRecommendations() ? 1 : 0)
			.register(registry);
		for (Algorithm algorithm : Algorithm.values()) {
			Gauge.builder("ratelimiter_adaptive_recommended_algorithm",
					() -> adaptiveRecommendedAlgorithm.get() == algorithm ? 1 : 0)
				.tag("algorithm", algorithm.toJson())
				.register(registry);
		}
		Gauge.builder("ratelimiter_adaptive_recommended_limit", adaptiveRecommendedLimit, value -> value.get())
			.register(registry);
		Gauge.builder("ratelimiter_adaptive_recommended_window_seconds",
				adaptiveRecommendedWindowSeconds, value -> value.get())
			.register(registry);
		Gauge.builder("ratelimiter_adaptive_recommended_capacity", adaptiveRecommendedCapacity, value -> value.get())
			.register(registry);
		Gauge.builder("ratelimiter_adaptive_recommended_fill_rate",
				adaptiveRecommendedFillRate, value -> value.get())
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

	public void recordAdaptiveRecommendation(RateLimiterConfigPayload payload, boolean applied) {
		if (payload == null) {
			return;
		}
		if (applied) {
			adaptiveApplied.increment();
		} else {
			adaptiveShadow.increment();
		}

		Algorithm algorithm = payload.getAlgorithm();
		if (algorithm != null) {
			String mode = applied ? "applied" : "shadow";
			Counter algorithmCounter = adaptiveByAlgorithm.get(mode + ":" + algorithm.name());
			if (algorithmCounter != null) {
				algorithmCounter.increment();
			}
			adaptiveRecommendedAlgorithm.set(algorithm);
		}
		adaptiveRecommendedLimit.set(payload.getLimit() != null ? payload.getLimit() : 0L);
		adaptiveRecommendedWindowSeconds.set(payload.getWindow() != null ? payload.getWindow() : 0L);
		adaptiveRecommendedCapacity.set(payload.getCapacity() != null ? payload.getCapacity() : 0L);
		adaptiveRecommendedFillRate.set(payload.getFillRate() != null ? payload.getFillRate() : 0.0);
	}

	public double getRequestLatencyP95() {
		HistogramSnapshot snapshot = requestTimer.takeSnapshot();
		for (ValueAtPercentile percentile : snapshot.percentileValues()) {
			if (percentile.percentile() == 0.95) {
				return percentile.value() / 1_000_000_000.0;
			}
		}
		return snapshot.max() / 1_000_000_000.0;
	}
}
