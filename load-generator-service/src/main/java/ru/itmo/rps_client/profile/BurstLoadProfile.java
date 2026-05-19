package ru.itmo.rps_client.profile;

import java.time.Duration;

public class BurstLoadProfile implements LoadProfile {
    private final double baseRps;
    private final double spikeRps;
    private final Duration spikeDuration;
    private final Duration spikePeriod;

    public BurstLoadProfile(double baseRps, double spikeRps, Duration spikeDuration, Duration spikePeriod) {
        this.baseRps = baseRps;
        this.spikeRps = spikeRps;
        this.spikeDuration = spikeDuration;
        this.spikePeriod = spikePeriod;
    }

    @Override
    public double currentRps(Duration elapsed) {
        long periodMillis = spikePeriod.toMillis();
        if (periodMillis <= 0) {
            return baseRps;
        }
        long within = Math.floorMod(elapsed.toMillis(), periodMillis);
        return within < spikeDuration.toMillis() ? spikeRps : baseRps;
    }

    @Override
    public String name() {
        return "burst";
    }
}
