package ru.itmo.rps_client.profile.params;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import java.time.Duration;
import ru.itmo.rps_client.config.DurationDeserializer;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BurstParams(
        double baseRps,
        double spikeRps,
        @JsonDeserialize(using = DurationDeserializer.class) Duration spikeDuration,
        @JsonDeserialize(using = DurationDeserializer.class) Duration spikePeriod
) {
}
