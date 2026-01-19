package ru.itmo.rps_client.profile;

import java.time.Duration;

public class SinusoidalLoadProfile implements LoadProfile {
    private final double minRps;
    private final double maxRps;
    private final Duration period;

    public SinusoidalLoadProfile(double minRps, double maxRps, Duration period) {
        this.minRps = minRps;
        this.maxRps = maxRps;
        this.period = period;
    }

    @Override
    public double currentRps(Duration elapsed) {
        long periodMillis = period.toMillis();
        if (periodMillis <= 0) {
            return minRps;
        }
        double mid = (minRps + maxRps) / 2.0;
        double amplitude = (maxRps - minRps) / 2.0;
        double radians = 2.0 * Math.PI * (elapsed.toMillis() / (double) periodMillis);
        return mid + amplitude * Math.sin(radians);
    }

    @Override
    public String name() {
        return "sinusoidal";
    }
}
