package ru.itmo.rate_limiter_service.metrics;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentSkipListMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;
import org.springframework.stereotype.Component;

@Component
public class TrafficStats {
	private static final long SECOND_BUCKET_RETENTION_SECONDS = 600;

	private final LongAdder total = new LongAdder();
	private final LongAdder rejected = new LongAdder();
	private final LongAdder errors5xx = new LongAdder();
	private final AtomicLong lastSnapshotNanos = new AtomicLong(System.nanoTime());
	private final ConcurrentSkipListMap<Long, SecondBucket> secondBuckets = new ConcurrentSkipListMap<>();

	public void recordDecision(boolean allowed, int statusCode) {
		total.increment();
		if (!allowed) {
			rejected.increment();
		} else if (statusCode >= 500 && statusCode <= 599) {
			errors5xx.increment();
		}

		SecondBucket bucket = secondBuckets.computeIfAbsent(Instant.now().getEpochSecond(), ignored -> new SecondBucket());
		bucket.record(allowed);
	}

	public void resetSnapshotState() {
		total.sumThenReset();
		rejected.sumThenReset();
		errors5xx.sumThenReset();
		lastSnapshotNanos.set(System.nanoTime());
		pruneOldBuckets(Instant.now().getEpochSecond());
	}

	public TrafficSnapshot snapshotAndReset(Duration interval) {
		long totalCount = total.sumThenReset();
		long rejectedCount = rejected.sumThenReset();
		long errorsCount = errors5xx.sumThenReset();
		long nowNanos = System.nanoTime();
		long lastNanos = lastSnapshotNanos.getAndSet(nowNanos);
		long fallbackNanos = interval.toNanos();
		if (fallbackNanos <= 0) {
			fallbackNanos = 1_000_000_000L;
		}
		long elapsedNanos = lastNanos > 0 ? nowNanos - lastNanos : fallbackNanos;
		if (elapsedNanos <= 0) {
			elapsedNanos = fallbackNanos;
		}

		double seconds = elapsedNanos / 1_000_000_000.0;
		double observedRps = totalCount / seconds;
		double allowedRps = (totalCount - rejectedCount) / seconds;
		double rejectedRps = rejectedCount / seconds;
		double rejectedRate = totalCount == 0 ? 0.0 : (double) rejectedCount / totalCount;

		long nowSecond = Instant.now().getEpochSecond();
		long windowSeconds = Math.max(1L, (long) Math.ceil(seconds));
		long fromSecond = nowSecond - windowSeconds + 1;

		double peakRps1s = 0.0;
		double squaredDeltaSum = 0.0;
		for (long second = fromSecond; second <= nowSecond; second++) {
			SecondBucket bucket = secondBuckets.get(second);
			double value = bucket == null ? 0.0 : bucket.total();
			peakRps1s = Math.max(peakRps1s, value);
			double delta = value - observedRps;
			squaredDeltaSum += delta * delta;
		}

		double stddev = Math.sqrt(squaredDeltaSum / windowSeconds);
		double coefficientOfVariation = observedRps <= 0 ? 0.0 : stddev / observedRps;
		double burstRatio = observedRps <= 0 ? 0.0 : peakRps1s / observedRps;

		pruneOldBuckets(nowSecond);
		return new TrafficSnapshot(
			observedRps,
			allowedRps,
			rejectedRps,
			rejectedRate,
			peakRps1s,
			burstRatio,
			coefficientOfVariation,
			errorsCount);
	}

	private void pruneOldBuckets(long nowSecond) {
		secondBuckets.headMap(nowSecond - SECOND_BUCKET_RETENTION_SECONDS, false).clear();
	}

	private static final class SecondBucket {
		private final LongAdder total = new LongAdder();

		void record(boolean allowed) {
			total.increment();
		}

		long total() {
			return total.sum();
		}
	}

	public record TrafficSnapshot(
		double observedRps,
		double allowedRps,
		double rejectedRps,
		double rejectedRate,
		double peakRps1s,
		double burstRatio,
		double coefficientOfVariation,
		long errors5xx
	) {
	}
}
