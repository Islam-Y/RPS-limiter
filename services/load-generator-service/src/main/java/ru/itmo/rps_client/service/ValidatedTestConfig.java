package ru.itmo.rps_client.service;

import java.net.URI;
import ru.itmo.rps_client.config.TestConfig;
import ru.itmo.rps_client.profile.LoadProfile;

public record ValidatedTestConfig(
        TestConfig config,
        URI targetUri,
        LoadProfile profile,
        Integer concurrency
) {
}
