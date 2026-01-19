package ru.itmo.rps_client.profile;

import java.time.Duration;

public interface LoadProfile {
    double currentRps(Duration elapsed);

    default Duration nextDelay(Duration elapsed) {
        double rps = currentRps(elapsed);
        if (rps <= 0) {
            return Duration.ofSeconds(1);
        }
        long nanos = (long) (1_000_000_000L / rps);
        return Duration.ofNanos(Math.max(0L, nanos));
    }

    String name();
}
