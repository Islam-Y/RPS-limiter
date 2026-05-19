package ru.itmo.rps_client.config;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.Duration;

public record TestConfig(
        @NotBlank String targetUrl,
        @NotNull @JsonDeserialize(using = DurationDeserializer.class) Duration duration,
        @NotNull @Valid ProfileConfig profile,
        @JsonAlias({"requestsPerThread"}) Integer concurrency
) {
}
