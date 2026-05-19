package ru.itmo.rate_limiter_service.model;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

public enum Algorithm {
	FIXED("fixed"),
	SLIDING("sliding"),
	TOKEN("token");

	private final String jsonValue;

	Algorithm(String jsonValue) {
		this.jsonValue = jsonValue;
	}

	@JsonCreator
	public static Algorithm fromJson(String value) {
		if (value == null) {
			return null;
		}
		return switch (value.toLowerCase()) {
			case "fixed" -> FIXED;
			case "sliding" -> SLIDING;
			case "token", "token_bucket", "token-bucket" -> TOKEN;
			default -> throw new IllegalArgumentException("Unsupported algorithm: " + value);
		};
	}

	@JsonValue
	public String toJson() {
		return jsonValue;
	}
}
