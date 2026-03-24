package ru.itmo.rps_client.profile;

import java.time.Duration;
import java.util.List;

public class PhasedLoadProfile implements LoadProfile {
    private final List<Phase> phases;

    public PhasedLoadProfile(List<Phase> phases) {
        this.phases = List.copyOf(phases);
    }

    @Override
    public double currentRps(Duration elapsed) {
        ActivePhase activePhase = resolve(elapsed);
        if (activePhase == null) {
            return 0.0;
        }
        return activePhase.phase().profile().currentRps(activePhase.localElapsed());
    }

    @Override
    public Duration nextDelay(Duration elapsed) {
        ActivePhase activePhase = resolve(elapsed);
        if (activePhase == null) {
            return LoadProfile.super.nextDelay(elapsed);
        }
        return activePhase.phase().profile().nextDelay(activePhase.localElapsed());
    }

    @Override
    public String name() {
        return "phased";
    }

    private ActivePhase resolve(Duration elapsed) {
        if (phases.isEmpty()) {
            return null;
        }
        Duration safeElapsed = elapsed.isNegative() ? Duration.ZERO : elapsed;
        Duration offset = Duration.ZERO;
        for (Phase phase : phases) {
            Duration end = offset.plus(phase.duration());
            if (safeElapsed.compareTo(end) < 0) {
                return new ActivePhase(phase, safeElapsed.minus(offset));
            }
            offset = end;
        }
        Phase last = phases.get(phases.size() - 1);
        return new ActivePhase(last, safeElapsed.minus(offset.minus(last.duration())));
    }

    private record ActivePhase(Phase phase, Duration localElapsed) {
    }

    public record Phase(String name, Duration duration, LoadProfile profile) {
    }
}
