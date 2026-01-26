package ru.itmo.rate_limiter_service.config;

import java.time.Duration;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import ru.itmo.rate_limiter_service.model.Algorithm;

@Getter
@Setter
@ConfigurationProperties(prefix = "ratelimiter")
public class RateLimiterProperties {
	private String targetUrl = "http://localhost:8081";
	private Algorithm algorithm = Algorithm.FIXED;
	private long limit = 100;
	private long windowSeconds = 60;
	private long capacity = 100;
	private double fillRate = 10.0;
	private boolean failOpen = true;
	private String configKey = "ratelimiter:config";
	private boolean loadConfigFromRedis = true;
	private boolean storeConfigInRedis = true;
	private Duration redisHealthInterval = Duration.ofSeconds(5);
	private Duration configRefreshInterval = Duration.ofSeconds(30);
	private Bounds bounds = new Bounds();
	private AdaptiveProperties adaptive = new AdaptiveProperties();

	@Getter
	@Setter
	public static class Bounds {
		private long minLimit = 1;
		private long maxLimit = 1_000_000;
		private long minWindowSeconds = 1;
		private long maxWindowSeconds = 3600;
		private long minCapacity = 1;
		private long maxCapacity = 1_000_000;
		private double minFillRate = 0.1;
		private double maxFillRate = 1_000_000;
	}

	@Getter
	@Setter
	public static class AdaptiveProperties {
		private boolean enabled = false;
		private String url;
		private Duration interval = Duration.ofSeconds(30);
		private Duration timeout = Duration.ofSeconds(5);
	}
}
