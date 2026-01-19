package ru.itmo.rps_client;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class RpsClientApplication {

	public static void main(String[] args) {
		SpringApplication.run(RpsClientApplication.class, args);
	}

}
