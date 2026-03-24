package ru.itmo.rps_client.profile.params;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import java.time.Duration;
import java.util.Map;
import ru.itmo.rps_client.config.DurationDeserializer;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PhasedStageParams(
        String name,
        @JsonDeserialize(using = DurationDeserializer.class) Duration duration,
        String type,
        Map<String, Object> params
) {
}
