package ru.itmo.rps_client.profile.params;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record PhasedParams(
        List<PhasedStageParams> phases
) {
}
