package in.drugwatch.api.shared;

/**
 * Something the caller asked for by id does not exist.
 *
 * <p>Its own type so that {@code GlobalExceptionHandler} can answer 404 without the service layer
 * having to know what HTTP is - which is the layering ArchUnit enforces.
 */
public class NotFoundException extends RuntimeException {
    public NotFoundException(String message) {
        super(message);
    }
}
