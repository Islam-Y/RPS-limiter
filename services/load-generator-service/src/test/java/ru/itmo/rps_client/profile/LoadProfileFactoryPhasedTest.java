package ru.itmo.rps_client.profile;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import ru.itmo.rps_client.config.ProfileConfig;
import ru.itmo.rps_client.exception.InvalidConfigurationException;

class LoadProfileFactoryPhasedTest {
    private final LoadProfileFactory factory = new LoadProfileFactory(new ObjectMapper());

    @Test
    void supportsPhasedProfileAndTransitionsBetweenStages() {
        ProfileConfig config = new ProfileConfig(
                "phased",
                Map.of(
                        "phases", List.of(
                                Map.of(
                                        "name", "warmup",
                                        "duration", "PT5S",
                                        "type", "constant",
                                        "params", Map.of("rps", 40)
                                ),
                                Map.of(
                                        "name", "attack",
                                        "duration", "PT6S",
                                        "type", "burst",
                                        "params", Map.of(
                                                "baseRps", 40,
                                                "spikeRps", 280,
                                                "spikeDuration", "PT2S",
                                                "spikePeriod", "PT6S"
                                        )
                                ),
                                Map.of(
                                        "name", "recovery",
                                        "duration", "PT5S",
                                        "type", "constant",
                                        "params", Map.of("rps", 40)
                                )
                        )
                )
        );

        LoadProfile profile = factory.create(config);

        assertEquals(40.0, profile.currentRps(Duration.ofSeconds(0)));
        assertEquals(40.0, profile.currentRps(Duration.ofSeconds(4)));
        assertEquals(280.0, profile.currentRps(Duration.ofSeconds(5)));
        assertEquals(40.0, profile.currentRps(Duration.ofSeconds(8)));
        assertEquals(40.0, profile.currentRps(Duration.ofSeconds(13)));
    }

    @Test
    void rejectsEmptyPhasedProfile() {
        ProfileConfig config = new ProfileConfig("phased", Map.of("phases", List.of()));
        assertThrows(InvalidConfigurationException.class, () -> factory.create(config));
    }

    @Test
    void delegatesNextDelayToActivePhaseProfile() {
        LoadProfile first = new LoadProfile() {
            @Override
            public double currentRps(Duration elapsed) {
                return 1.0;
            }

            @Override
            public Duration nextDelay(Duration elapsed) {
                return Duration.ofMillis(250);
            }

            @Override
            public String name() {
                return "first";
            }
        };
        LoadProfile second = new LoadProfile() {
            @Override
            public double currentRps(Duration elapsed) {
                return 1.0;
            }

            @Override
            public Duration nextDelay(Duration elapsed) {
                return Duration.ofMillis(25);
            }

            @Override
            public String name() {
                return "second";
            }
        };
        PhasedLoadProfile profile = new PhasedLoadProfile(List.of(
                new PhasedLoadProfile.Phase("warmup", Duration.ofSeconds(5), first),
                new PhasedLoadProfile.Phase("attack", Duration.ofSeconds(5), second)
        ));

        assertEquals(Duration.ofMillis(250), profile.nextDelay(Duration.ofSeconds(2)));
        assertEquals(Duration.ofMillis(25), profile.nextDelay(Duration.ofSeconds(7)));
    }
}
