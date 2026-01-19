package ru.itmo.rps_client.config;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record ProfileConfig(
        @NotBlank String type,
        @NotNull JsonNode params
) {
}
