package acme.beta;

public class Parser {
    public String[] tokens(String expression) {
        return expression.trim().split("\\s+");
    }
}
