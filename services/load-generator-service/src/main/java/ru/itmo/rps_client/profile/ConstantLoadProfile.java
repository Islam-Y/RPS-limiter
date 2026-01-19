package ru.itmo.rps_client.profile;

import java.time.Duration;

public class ConstantLoadProfile implements LoadProfile {
    private final double rps;

    public ConstantLoadProfile(double rps) {
        this.rps = rps;
    }

    @Override
    public double currentRps(Duration elapsed) {
        return rps;
    }

    @Override
    public String name() {
        return "constant";
    }
}
