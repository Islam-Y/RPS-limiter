package ru.itmo.rps_client.profile;

import java.time.Duration;
import java.util.concurrent.ThreadLocalRandom;

public class PoissonLoadProfile implements LoadProfile {
    private final double averageRps;

    public PoissonLoadProfile(double averageRps) {
        this.averageRps = averageRps;
    }

    @Override
    public double currentRps(Duration elapsed) {
        return averageRps;
    }

    @Override
    public Duration nextDelay(Duration elapsed) {
        if (averageRps <= 0) {
            return Duration.ofSeconds(1);
        }
        double u = ThreadLocalRandom.current().nextDouble();
        double delaySeconds = -Math.log(1.0 - u) / averageRps;
        long nanos = (long) (delaySeconds * 1_000_000_000L);
        return Duration.ofNanos(Math.max(0L, nanos));
    }

    @Override
    public String name() {
        return "poisson";
    }
}
