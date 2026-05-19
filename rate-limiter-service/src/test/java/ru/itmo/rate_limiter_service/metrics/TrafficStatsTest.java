package ru.itmo.rate_limiter_service.metrics;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import org.junit.jupiter.api.Test;

class TrafficStatsTest {

	@Test
	void snapshotIncludesExpandedBurstTelemetry() throws Exception {
		// Arrange
		TrafficStats trafficStats = new TrafficStats();
		trafficStats.resetSnapshotState();
		Thread.sleep(1100);
		trafficStats.recordDecision(true, 200);
		trafficStats.recordDecision(true, 200);
		trafficStats.recordDecision(false, 429);

		// Act
		TrafficStats.TrafficSnapshot snapshot = trafficStats.snapshotAndReset(Duration.ofSeconds(1));

		// Assert
		assertTrue(snapshot.observedRps() > 0.0);
		assertTrue(snapshot.allowedRps() > 0.0);
		assertTrue(snapshot.rejectedRps() > 0.0);
		assertTrue(snapshot.peakRps1s() >= 1.0);
		assertTrue(snapshot.burstRatio() > 0.0);
		assertTrue(snapshot.coefficientOfVariation() >= 0.0);
		assertEquals(1.0 / 3.0, snapshot.rejectedRate(), 0.05);
	}
}
