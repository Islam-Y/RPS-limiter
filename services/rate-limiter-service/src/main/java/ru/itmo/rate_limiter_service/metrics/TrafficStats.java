package ru.itmo.rate_limiter_service.metrics;

import java.time.Duration;
import java.util.concurrent.atomic.LongAdder;
import org.springframework.stereotype.Component;

@Component
public class TrafficStats {
	private final LongAdder total = new LongAdder();
	private final LongAdder rejected = new LongAdder();
	private final LongAdder errors5xx = new LongAdder();

	public void recordDecision(boolean allowed, int statusCode) {
		total.increment();
		if (!allowed) {
			rejected.increment();
		} else if (statusCode >= 500 && statusCode <= 599) {
			errors5xx.increment();
		}
	}

	public TrafficSnapshot snapshotAndReset(Duration interval) {
		long totalCount = total.sumThenReset();
		long rejectedCount = rejected.sumThenReset();
		long errorsCount = errors5xx.sumThenReset();
		double seconds = Math.max(1.0, interval.toMillis() / 1000.0);
		double rps = totalCount / seconds;
		double rejectedRate = totalCount == 0 ? 0.0 : (double) rejectedCount / totalCount;
		return new TrafficSnapshot(rps, rejectedRate, errorsCount);
	}

	public record TrafficSnapshot(double observedRps, double rejectedRate, long errors5xx) {
	}
}
