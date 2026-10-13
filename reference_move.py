"""Reference wrapper for the movement snippet's visible behavior."""
n, m = map(int, input().split())
x = y = success = failure = 0
for _ in range(m):
    command = input().strip()
    next_x, next_y = x, y
    is_move = False
    match command:
        case "R":
            next_x += 1
            is_move = True
        case "L":
            next_x -= 1
            is_move = True
        case "U":
            next_y += 1
            is_move = True
        case "D":
            next_y -= 1
            is_move = True
        case "H":
            x = y = 0
        case _:
            failure += 1
    if is_move:
        if 0 <= next_x < n and 0 <= next_y < n:
            x, y = next_x, next_y
            success += 1
        else:
            failure += 1
print(x, y)
print(success)
print(failure)
