package acme.beta;

public class Calculator {
    public double apply(String operator, double left, double right) {
        switch (operator) {
            case "+":
                return left + right;
            case "-":
                return left - right;
            case "*":
                return left * right;
            case "/":
                if (right == 0) {
                    throw new ArithmeticException("division by zero");
                }
                return left / right;
            default:
                throw new IllegalArgumentException("unknown operator " + operator);
        }
    }
}
