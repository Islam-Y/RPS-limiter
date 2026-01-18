package ru.itmo.rps_client.profile;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.Locale;
import org.springframework.stereotype.Component;
import ru.itmo.rps_client.config.ProfileConfig;
import ru.itmo.rps_client.exception.InvalidConfigurationException;
import ru.itmo.rps_client.profile.params.BurstParams;
import ru.itmo.rps_client.profile.params.ConstantParams;
import ru.itmo.rps_client.profile.params.DdosParams;
import ru.itmo.rps_client.profile.params.PoissonParams;
import ru.itmo.rps_client.profile.params.SinusoidalParams;

@Component
public class LoadProfileFactory {
    private final ObjectMapper objectMapper;

    public LoadProfileFactory(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public LoadProfile create(ProfileConfig profileConfig) {
        if (profileConfig == null || profileConfig.type() == null) {
            throw new InvalidConfigurationException("Profile type is required");
        }
        String type = profileConfig.type().toLowerCase(Locale.ROOT).trim();
        return switch (type) {
            case "constant" -> createConstant(profileConfig.params());
            case "burst" -> createBurst(profileConfig.params());
            case "sinusoidal" -> createSinusoidal(profileConfig.params());
            case "poisson" -> createPoisson(profileConfig.params());
            case "ddos" -> createDdos(profileConfig.params());
            default -> throw new InvalidConfigurationException("Unsupported profile type: " + profileConfig.type());
        };
    }

    private LoadProfile createConstant(JsonNode params) {
        requireParams(params, "rps");
        ConstantParams parsed = objectMapper.convertValue(params, ConstantParams.class);
        requirePositive(parsed.rps(), "rps");
        return new ConstantLoadProfile(parsed.rps());
    }

    private LoadProfile createBurst(JsonNode params) {
        requireParams(params, "baseRps", "spikeRps", "spikeDuration", "spikePeriod");
        BurstParams parsed = objectMapper.convertValue(params, BurstParams.class);
        requireNonNegative(parsed.baseRps(), "baseRps");
        requirePositive(parsed.spikeRps(), "spikeRps");
        requireDurationPositive(parsed.spikeDuration(), "spikeDuration");
        requireDurationPositive(parsed.spikePeriod(), "spikePeriod");
        if (parsed.spikeDuration().compareTo(parsed.spikePeriod()) > 0) {
            throw new InvalidConfigurationException("spikeDuration must be <= spikePeriod");
        }
        return new BurstLoadProfile(parsed.baseRps(), parsed.spikeRps(), parsed.spikeDuration(), parsed.spikePeriod());
    }

    private LoadProfile createSinusoidal(JsonNode params) {
        requireParams(params, "minRps", "maxRps", "period");
        SinusoidalParams parsed = objectMapper.convertValue(params, SinusoidalParams.class);
        requireNonNegative(parsed.minRps(), "minRps");
        requirePositive(parsed.maxRps(), "maxRps");
        if (parsed.maxRps() < parsed.minRps()) {
            throw new InvalidConfigurationException("maxRps must be >= minRps");
        }
        requireDurationPositive(parsed.period(), "period");
        return new SinusoidalLoadProfile(parsed.minRps(), parsed.maxRps(), parsed.period());
    }

    private LoadProfile createPoisson(JsonNode params) {
        requireParams(params, "averageRps");
        PoissonParams parsed = objectMapper.convertValue(params, PoissonParams.class);
        requirePositive(parsed.averageRps(), "averageRps");
        return new PoissonLoadProfile(parsed.averageRps());
    }

    private LoadProfile createDdos(JsonNode params) {
        requireParams(params, "minRps", "maxRps", "maxSpikeDuration", "minIdleTime", "maxIdleTime");
        DdosParams parsed = objectMapper.convertValue(params, DdosParams.class);
        requireNonNegative(parsed.minRps(), "minRps");
        requirePositive(parsed.maxRps(), "maxRps");
        if (parsed.maxRps() < parsed.minRps()) {
            throw new InvalidConfigurationException("maxRps must be >= minRps");
        }
        requireDurationPositive(parsed.maxSpikeDuration(), "maxSpikeDuration");
        requireDurationNonNegative(parsed.minIdleTime(), "minIdleTime");
        requireDurationNonNegative(parsed.maxIdleTime(), "maxIdleTime");
        if (parsed.maxIdleTime().compareTo(parsed.minIdleTime()) < 0) {
            throw new InvalidConfigurationException("maxIdleTime must be >= minIdleTime");
        }
        return new DdosLoadProfile(parsed.minRps(), parsed.maxRps(), parsed.maxSpikeDuration(),
                parsed.minIdleTime(), parsed.maxIdleTime());
    }

    private void requireParams(JsonNode params, String... names) {
        if (params == null || params.isNull()) {
            throw new InvalidConfigurationException("Profile params are required");
        }
        for (String name : names) {
            if (!params.hasNonNull(name)) {
                throw new InvalidConfigurationException("Missing required param: " + name);
            }
        }
    }

    private void requirePositive(double value, String name) {
        if (value <= 0) {
            throw new InvalidConfigurationException(name + " must be > 0");
        }
    }

    private void requireNonNegative(double value, String name) {
        if (value < 0) {
            throw new InvalidConfigurationException(name + " must be >= 0");
        }
    }

    private void requireDurationPositive(Duration value, String name) {
        if (value == null || value.isZero() || value.isNegative()) {
            throw new InvalidConfigurationException(name + " must be > 0");
        }
    }

    private void requireDurationNonNegative(Duration value, String name) {
        if (value == null || value.isNegative()) {
            throw new InvalidConfigurationException(name + " must be >= 0");
        }
    }
}
