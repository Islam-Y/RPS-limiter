package ru.itmo.rps_client.config;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.util.Map;

public record ProfileConfig(
        @NotBlank String type,
        @NotNull Map<String, Object> params
) {
}
