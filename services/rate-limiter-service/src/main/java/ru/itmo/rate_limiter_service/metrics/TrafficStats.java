package ru.itmo.rate_limiter_service.metrics;

import java.time.Duration;
import java.util.concurrent.atomic.LongAdder;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

@Component
public class TrafficStats {
	private final LongAdder total = new LongAdder();
	private final LongAdder rejected = new LongAdder();
	private final LongAdder errors5xx = new LongAdder();
	private final AtomicLong lastSnapshotNanos = new AtomicLong(System.nanoTime());

	public void recordDecision(boolean allowed, int statusCode) {
		total.increment();
		if (!allowed) {
			rejected.increment();
		} else if (statusCode >= 500 && statusCode <= 599) {
			errors5xx.increment();
		}
	}

	public void resetSnapshotState() {
		total.sumThenReset();
		rejected.sumThenReset();
		errors5xx.sumThenReset();
		lastSnapshotNanos.set(System.nanoTime());
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
		double rps = totalCount / seconds;
		double rejectedRate = totalCount == 0 ? 0.0 : (double) rejectedCount / totalCount;
		return new TrafficSnapshot(rps, rejectedRate, errorsCount);
	}

	public record TrafficSnapshot(double observedRps, double rejectedRate, long errors5xx) {
	}
}
