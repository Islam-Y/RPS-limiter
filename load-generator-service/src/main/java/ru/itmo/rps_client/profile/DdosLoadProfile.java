package ru.itmo.rps_client.profile;

import java.time.Duration;
import java.util.concurrent.ThreadLocalRandom;

public class DdosLoadProfile implements LoadProfile {
    private final double minRps;
    private final double maxRps;
    private final Duration maxSpikeDuration;
    private final Duration minIdleTime;
    private final Duration maxIdleTime;

    private boolean inSpike = false;
    private long segmentEndMillis = 0;

    public DdosLoadProfile(double minRps,
                           double maxRps,
                           Duration maxSpikeDuration,
                           Duration minIdleTime,
                           Duration maxIdleTime) {
        this.minRps = minRps;
        this.maxRps = maxRps;
        this.maxSpikeDuration = maxSpikeDuration;
        this.minIdleTime = minIdleTime;
        this.maxIdleTime = maxIdleTime;
    }

    @Override
    public double currentRps(Duration elapsed) {
        long nowMillis = elapsed.toMillis();
        if (segmentEndMillis == 0) {
            segmentEndMillis = nowMillis + randomIdleMillis();
            inSpike = false;
        }
        if (nowMillis >= segmentEndMillis) {
            if (inSpike) {
                inSpike = false;
                segmentEndMillis = nowMillis + randomIdleMillis();
            } else {
                inSpike = true;
                segmentEndMillis = nowMillis + randomSpikeMillis();
            }
        }
        return inSpike ? maxRps : minRps;
    }

    @Override
    public String name() {
        return "ddos";
    }

    private long randomSpikeMillis() {
        long maxMs = Math.max(1L, maxSpikeDuration.toMillis());
        return ThreadLocalRandom.current().nextLong(1L, maxMs + 1L);
    }

    private long randomIdleMillis() {
        long minMs = Math.max(0L, minIdleTime.toMillis());
        long maxMs = Math.max(minMs, maxIdleTime.toMillis());
        if (minMs == maxMs) {
            return minMs;
        }
        return ThreadLocalRandom.current().nextLong(minMs, maxMs + 1L);
    }
}
