package ru.itmo.rps_client.config;

import jakarta.validation.constraints.PositiveOrZero;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "loadgen")
public class LoadGeneratorProperties {
    private Duration tick = Duration.ofMillis(100);
    private Duration logInterval = Duration.ofSeconds(10);
    private final HttpProperties http = new HttpProperties();
    @PositiveOrZero
    private int defaultConcurrency = 0;
    private String configFile;

    public Duration getTick() {
        return tick;
    }

    public void setTick(Duration tick) {
        this.tick = tick;
    }

    public Duration getLogInterval() {
        return logInterval;
    }

    public void setLogInterval(Duration logInterval) {
        this.logInterval = logInterval;
    }

    public HttpProperties getHttp() {
        return http;
    }

    public int getDefaultConcurrency() {
        return defaultConcurrency;
    }

    public void setDefaultConcurrency(int defaultConcurrency) {
        this.defaultConcurrency = defaultConcurrency;
    }

    public String getConfigFile() {
        return configFile;
    }

    public void setConfigFile(String configFile) {
        this.configFile = configFile;
    }

    public static class HttpProperties {
        private Duration timeout = Duration.ofSeconds(10);
        private Duration connectTimeout = Duration.ofSeconds(5);
        private Duration slowThreshold = Duration.ofSeconds(1);

        public Duration getTimeout() {
            return timeout;
        }

        public void setTimeout(Duration timeout) {
            this.timeout = timeout;
        }

        public Duration getConnectTimeout() {
            return connectTimeout;
        }

        public void setConnectTimeout(Duration connectTimeout) {
            this.connectTimeout = connectTimeout;
        }

        public Duration getSlowThreshold() {
            return slowThreshold;
        }

        public void setSlowThreshold(Duration slowThreshold) {
            this.slowThreshold = slowThreshold;
        }
    }
}
