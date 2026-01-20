package ru.itmo.rate_limiter_service;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;
import ru.itmo.rate_limiter_service.config.RateLimiterProperties;

@SpringBootApplication
@EnableScheduling
@EnableConfigurationProperties(RateLimiterProperties.class)
public class RateLimiterServiceApplication {

	public static void main(String[] args) {
		SpringApplication.run(RateLimiterServiceApplication.class, args);
	}

}
