package ru.itmo.rps_client.config;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.exc.InvalidFormatException;
import java.io.IOException;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.format.DateTimeParseException;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class DurationDeserializer extends JsonDeserializer<Duration> {
    private static final Pattern SIMPLE_DURATION = Pattern.compile("^(\\d+(?:\\.\\d+)?)(ms|s|m|h|d)?$");

    @Override
    public Duration deserialize(JsonParser parser, DeserializationContext context) throws IOException {
        JsonNode node = parser.getCodec().readTree(parser);
        if (node.isNumber()) {
            return fromSeconds(node.decimalValue());
        }
        if (node.isTextual()) {
            String raw = node.asText();
            try {
                return parse(raw);
            } catch (IllegalArgumentException ex) {
                throw InvalidFormatException.from(parser, ex.getMessage(), raw, Duration.class);
            }
        }
        throw InvalidFormatException.from(parser, "Duration must be a number (seconds) or a string", node, Duration.class);
    }

    private static Duration parse(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) {
            throw new IllegalArgumentException("Duration value is empty");
        }
        if (value.regionMatches(true, 0, "P", 0, 1)) {
            try {
                return Duration.parse(value.toUpperCase(Locale.ROOT));
            } catch (DateTimeParseException ex) {
                throw new IllegalArgumentException("Invalid ISO-8601 duration: " + raw, ex);
            }
        }
        Matcher matcher = SIMPLE_DURATION.matcher(value.toLowerCase(Locale.ROOT));
        if (!matcher.matches()) {
            throw new IllegalArgumentException("Invalid duration format: " + raw);
        }
        BigDecimal amount = new BigDecimal(matcher.group(1));
        String unit = matcher.group(2);
        if (unit == null || unit.isEmpty()) {
            unit = "s";
        }
        return switch (unit) {
            case "ms" -> Duration.ofNanos(amount.multiply(BigDecimal.valueOf(1_000_000L)).longValue());
            case "s" -> fromSeconds(amount);
            case "m" -> fromSeconds(amount.multiply(BigDecimal.valueOf(60L)));
            case "h" -> fromSeconds(amount.multiply(BigDecimal.valueOf(3600L)));
            case "d" -> fromSeconds(amount.multiply(BigDecimal.valueOf(86_400L)));
            default -> throw new IllegalArgumentException("Unsupported duration unit: " + unit);
        };
    }

    private static Duration fromSeconds(BigDecimal seconds) {
        return Duration.ofNanos(seconds.multiply(BigDecimal.valueOf(1_000_000_000L)).longValue());
    }
}
