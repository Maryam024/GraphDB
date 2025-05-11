import re
import operator

def evaluate_condition(row, condition):
    """Evaluate a WHERE condition against a row of data"""
    # Handle AND conditions (with precedence over OR)
    if ' AND ' in condition:
        parts = condition.split(' AND ')
        return all(evaluate_condition(row, part.strip()) for part in parts)
    
    # Handle OR conditions
    if ' OR ' in condition:
        parts = condition.split(' OR ')
        return any(evaluate_condition(row, part.strip()) for part in parts)
    
    # Handle NOT condition
    if condition.upper().startswith('NOT '):
        return not evaluate_condition(row, condition[4:].strip())
    
    # Handle parentheses for grouping and complex conditions
    if '(' in condition and ')' in condition:
        # Extract the expression inside parentheses
        open_idx = condition.find('(')
        close_idx = condition.rfind(')')
        if open_idx == 0 and close_idx == len(condition) - 1:
            # The entire condition is in parentheses, remove them and evaluate
            return evaluate_condition(row, condition[1:close_idx].strip())
    
    # Handle comparison operators
    # n.property > value
    comparison_match = re.match(r"(\w+)\.(\w+)\s*([=><!]+)\s*(.+)", condition)
    if comparison_match:
        var_name = comparison_match.group(1)
        prop_name = comparison_match.group(2)
        operator_str = comparison_match.group(3)
        value_str = comparison_match.group(4).strip()
        
        # Evaluate the right side value
        if value_str.startswith("'") and value_str.endswith("'"):
            value = value_str[1:-1]
        elif value_str.startswith('"') and value_str.endswith('"'):
            value = value_str[1:-1]
        elif value_str.lower() == 'true':
            value = True
        elif value_str.lower() == 'false':
            value = False
        elif value_str.isdigit():
            value = int(value_str)
        elif re.match(r'^-?\d+(\.\d+)?$', value_str):
            value = float(value_str)
        else:
            # Might be a variable reference
            if '.' in value_str:
                ref_var, ref_prop = value_str.split('.')
                if ref_var in row and hasattr(row[ref_var], 'properties'):
                    value = row[ref_var].properties.get(ref_prop)
                else:
                    value = value_str
            else:
                value = value_str
        
        # Get the property value from the node
        if var_name in row and hasattr(row[var_name], 'properties'):
            node = row[var_name]
            left_value = node.properties.get(prop_name)
            
            # Compare values based on operator
            # Handle None values for all comparison operators
            if left_value is None:
                # None values fail all numeric comparisons except != and <>
                if operator_str == '=':
                    return value is None
                elif operator_str == '>' or operator_str == '>=' or operator_str == '<' or operator_str == '<=':
                    return False
                elif operator_str == '<>':
                    return value is not None
                elif operator_str == '!=':
                    return value is not None
            else:
                # Normal comparison for non-None values
                if operator_str == '=':
                    return left_value == value
                elif operator_str == '>':
                    return left_value > value
                elif operator_str == '>=':
                    return left_value >= value
                elif operator_str == '<':
                    return left_value < value
                elif operator_str == '<=':
                    return left_value <= value
                elif operator_str == '<>':
                    return left_value != value
                elif operator_str == '!=':
                    return left_value != value
    
    # Handle EXISTS
    exists_match = re.match(r"EXISTS\((\w+)\.(\w+)\)", condition)
    if exists_match:
        var_name = exists_match.group(1)
        prop_name = exists_match.group(2)
        
        if var_name in row and hasattr(row[var_name], 'properties'):
            node = row[var_name]
            return prop_name in node.properties
    
    # Handle string operations like CONTAINS, STARTS WITH, ENDS WITH
    string_op_match = re.match(r"(\w+)\.(\w+)\s+(CONTAINS|STARTS WITH|ENDS WITH)\s+(.+)", condition, re.IGNORECASE)
    if string_op_match:
        var_name = string_op_match.group(1)
        prop_name = string_op_match.group(2)
        string_op = string_op_match.group(3).upper()
        value_str = string_op_match.group(4).strip()
        
        # Parse the string value
        if value_str.startswith("'") and value_str.endswith("'"):
            value = value_str[1:-1]
        elif value_str.startswith('"') and value_str.endswith('"'):
            value = value_str[1:-1]
        else:
            value = value_str
        
        if var_name in row and hasattr(row[var_name], 'properties'):
            node = row[var_name]
            prop_value = node.properties.get(prop_name)
            
            if prop_value is not None and isinstance(prop_value, str):
                if string_op == 'CONTAINS':
                    return value in prop_value
                elif string_op == 'STARTS WITH':
                    return prop_value.startswith(value)
                elif string_op == 'ENDS WITH':
                    return prop_value.endswith(value)
    
    # If nothing matched, return False
    return False
