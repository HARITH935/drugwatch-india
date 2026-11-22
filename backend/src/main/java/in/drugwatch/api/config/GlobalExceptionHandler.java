package in.drugwatch.api.config;

import in.drugwatch.api.auth.domain.InvalidCredentialsException;
import in.drugwatch.api.shared.NotFoundException;
import in.drugwatch.api.shared.PublicNotes;
import jakarta.validation.ConstraintViolationException;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * One place where errors become responses (plan §9 step 10).
 *
 * <p>The rule it enforces is that <b>an error tells the caller what to fix and tells an attacker
 * nothing</b>. A stack trace, a SQL message or a class name in a response body is free
 * reconnaissance: it names the database, the framework version and often the query. So a 500
 * carries a reference number, the detail goes to the log, and the two are tied together by that
 * number.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** A parameter was missing: the caller can fix this, so say exactly which. */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ResponseEntity<Map<String, Object>> missingParameter(MissingServletRequestParameterException error) {
        return problem(
                HttpStatus.BAD_REQUEST,
                "'%s' is required".formatted(error.getParameterName()),
                Map.of("parameter", error.getParameterName()));
    }

    /** A parameter was present but unusable - too short, too long, blank. */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<Map<String, Object>> invalidParameter(ConstraintViolationException error) {
        Map<String, Object> fields = new LinkedHashMap<>();
        error.getConstraintViolations().forEach(violation -> {
            String path = violation.getPropertyPath().toString();
            // "search.drug" to "drug": the method name is an internal detail.
            fields.put(path.substring(path.lastIndexOf('.') + 1), violation.getMessage());
        });
        return problem(HttpStatus.BAD_REQUEST, "One or more parameters are not valid", fields);
    }

    /**
     * Login, refresh or verification failed.
     *
     * <p>401 with one message for every cause: saying "no such account" and "wrong password"
     * separately is a way for anybody to find out who has an account on a site about the medicines
     * people take.
     */
    @ExceptionHandler(InvalidCredentialsException.class)
    public ResponseEntity<Map<String, Object>> invalidCredentials(InvalidCredentialsException error) {
        return problem(HttpStatus.UNAUTHORIZED, error.getMessage(), Map.of());
    }

    /** A request body failed validation. */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> invalidBody(MethodArgumentNotValidException error) {
        Map<String, Object> fields = new LinkedHashMap<>();
        error.getBindingResult()
                .getFieldErrors()
                .forEach(field -> fields.put(field.getField(), field.getDefaultMessage()));
        return problem(HttpStatus.BAD_REQUEST, "One or more fields are not valid", fields);
    }

    /** Asked for by id, does not exist. A plain 404 with no detail about what else might. */
    @ExceptionHandler(NotFoundException.class)
    public ResponseEntity<Map<String, Object>> notFound(NotFoundException error) {
        return problem(HttpStatus.NOT_FOUND, error.getMessage(), Map.of());
    }

    /**
     * Exceptions Spring raises that already carry the right HTTP status - an unknown path, an
     * unsupported method, a malformed body.
     *
     * <p>Without this, the catch-all below turns every one of them into a 500. That is exactly
     * what happened here: {@code /actuator/env} started answering 500 instead of 404 the moment
     * the catch-all was added, which would have hidden every framework-level error behind "500,
     * quote this reference" - and told an attacker that a path they guessed had *done* something.
     */
    @ExceptionHandler(ErrorResponseException.class)
    public ResponseEntity<Map<String, Object>> alreadyHasAStatus(ErrorResponseException error) {
        return problem(
                HttpStatus.valueOf(error.getStatusCode().value()),
                error.getBody().getTitle(),
                Map.of());
    }

    /** An unknown path. A plain 404, never a 500. */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, Object>> noSuchPath(NoResourceFoundException error) {
        return problem(HttpStatus.NOT_FOUND, "No such endpoint", Map.of());
    }

    /**
     * Anything unplanned. The caller gets a reference; the log gets the exception.
     *
     * <p>Without this, Spring's default response can include the exception message, which for a
     * database error is the failing SQL.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> unexpected(Exception error) {
        String reference = Long.toHexString(System.nanoTime());
        log.error("unhandled error [{}]", reference, error);
        return problem(
                HttpStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong on our side. Quote this reference if you report it.",
                Map.of("reference", reference));
    }

    private ResponseEntity<Map<String, Object>> problem(HttpStatus status, String message, Map<String, ?> detail) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", status.value());
        body.put("error", message);
        body.put("detail", detail);
        body.put("at", Instant.now().toString());
        // Carried even on an error: a client that only ever renders the error path still shows it.
        body.put("disclaimer", PublicNotes.DISCLAIMER);
        return ResponseEntity.status(status).body(body);
    }
}
