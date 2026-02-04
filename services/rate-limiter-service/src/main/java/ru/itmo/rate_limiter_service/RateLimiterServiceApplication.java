package ru.itmo.rate_limiter_service;

import java.security.Security;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;

@SpringBootApplication
@EnableScheduling
@EnableConfigurationProperties(RateLimiterProperties.class)
public class RateLimiterServiceApplication {
	static {
		Security.setProperty("networkaddress.cache.ttl", "30");
		Security.setProperty("networkaddress.cache.negative.ttl", "1");
	}

	public static void main(String[] args) {
		SpringApplication.run(RateLimiterServiceApplication.class, args);
	}

}
