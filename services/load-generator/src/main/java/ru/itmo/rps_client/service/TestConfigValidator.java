package ru.itmo.rps_client.service;

import java.net.URI;
import java.net.URISyntaxException;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import ru.itmo.rps_client.config.TestConfig;
import ru.itmo.rps_client.exception.InvalidConfigurationException;
import ru.itmo.rps_client.profile.LoadProfile;
import ru.itmo.rps_client.profile.LoadProfileFactory;

@Component
public class TestConfigValidator {
    private final LoadProfileFactory profileFactory;

    public TestConfigValidator(LoadProfileFactory profileFactory) {
        this.profileFactory = profileFactory;
    }

    public ValidatedTestConfig validate(TestConfig config) {
        if (config == null) {
            throw new InvalidConfigurationException("Test config is required");
        }
        if (!StringUtils.hasText(config.targetUrl())) {
            throw new InvalidConfigurationException("targetUrl is required");
        }
        URI targetUri = parseTargetUri(config.targetUrl());
        if (config.duration() == null || config.duration().isZero() || config.duration().isNegative()) {
            throw new InvalidConfigurationException("duration must be > 0");
        }
        if (config.concurrency() != null && config.concurrency() <= 0) {
            throw new InvalidConfigurationException("concurrency must be > 0");
        }
        LoadProfile profile = profileFactory.create(config.profile());
        return new ValidatedTestConfig(config, targetUri, profile, config.concurrency());
    }

    private URI parseTargetUri(String raw) {
        try {
            URI uri = new URI(raw);
            String scheme = uri.getScheme();
            if (scheme == null || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
                throw new InvalidConfigurationException("targetUrl must use http or https scheme");
            }
            if (uri.getHost() == null) {
                throw new InvalidConfigurationException("targetUrl must include host");
            }
            return uri;
        } catch (URISyntaxException ex) {
            throw new InvalidConfigurationException("Invalid targetUrl: " + raw);
        }
    }
}
