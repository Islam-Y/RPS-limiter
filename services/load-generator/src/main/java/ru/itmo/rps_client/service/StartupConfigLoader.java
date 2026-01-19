package ru.itmo.rps_client.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import ru.itmo.rps_client.config.LoadGeneratorProperties;
import ru.itmo.rps_client.config.TestConfig;

@Component
public class StartupConfigLoader implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(StartupConfigLoader.class);

    private final LoadGeneratorProperties properties;
    private final ObjectMapper mapper;
    private final LoadTestManager manager;

    public StartupConfigLoader(LoadGeneratorProperties properties,
                               ObjectMapper mapper,
                               LoadTestManager manager) {
        this.properties = properties;
        this.mapper = mapper;
        this.manager = manager;
    }

    @Override
    public void run(ApplicationArguments args) {
        String configPath = properties.getConfigFile();
        if (!StringUtils.hasText(configPath)) {
            return;
        }
        Path path = Path.of(configPath);
        if (!Files.isRegularFile(path)) {
            log.warn("Load test config file not found: {}", path.toAbsolutePath());
            return;
        }
        try {
            TestConfig config = mapper.readValue(path.toFile(), TestConfig.class);
            log.info("Starting load test from config file {}", path.toAbsolutePath());
            manager.start(config);
        } catch (IOException ex) {
            throw new IllegalStateException("Failed to read load test config file: " + path.toAbsolutePath(), ex);
        }
    }
}
