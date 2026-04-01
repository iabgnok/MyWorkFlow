import pandas as pd
import argparse
import sys

def calculate_column_average(csv_file_path, column_name):
    """
    读取一个 CSV 文件，计算其中指定列的平均值。

    Args:
        csv_file_path (str): CSV 文件的路径。
        column_name (str): 需要计算平均值的列名。

    Returns:
        float or None: 如果成功，返回列的平均值；否则返回 None，并输出错误信息。
    """
    try:
        df = pd.read_csv(csv_file_path)
    except FileNotFoundError:
        print(f"错误: 文件 '{csv_file_path}' 不存在。", file=sys.stderr)
        return None
    except pd.errors.EmptyDataError:
        print(f"错误: 文件 '{csv_file_path}' 为空，无法读取数据。", file=sys.stderr)
        return None
    except pd.errors.ParserError as e:
        print(f"错误: 解析 CSV 文件 '{csv_file_path}' 时发生错误: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"错误: 读取文件 '{csv_file_path}' 时发生未知错误: {e}", file=sys.stderr)
        return None

    if column_name not in df.columns:
        print(f"错误: 列 '{column_name}' 不存在于文件 '{csv_file_path}' 中。", file=sys.stderr)
        print(f"可用的列名有: {list(df.columns)}", file=sys.stderr)
        return None

    # 尝试将指定列转换为数值类型，无法转换的值将变为 NaN
    numeric_column = pd.to_numeric(df[column_name], errors='coerce')

    # 检查转换后的列是否全部是 NaN (表示没有有效的数值数据)
    if numeric_column.isnull().all():
        print(f"错误: 列 '{column_name}' 不包含任何可转换为数字的数据。", file=sys.stderr)
        return None

    # 计算平均值，自动忽略 NaN 值
    average = numeric_column.mean()

    return average

def main():
    parser = argparse.ArgumentParser(
        description="一个用于计算 CSV 文件中指定列平均值的脚本。",
        epilog="示例: python your_script_name.py data.csv '销售额'"
    )
    parser.add_argument(
        "csv_file_path",
        type=str,
        help="要处理的 CSV 文件的路径。"
    )
    parser.add_argument(
        "column_name",
        type=str,
        help="需要计算平均值的列的名称。"
    )

    args = parser.parse_args()

    average_value = calculate_column_average(args.csv_file_path, args.column_name)

    if average_value is not None:
        print(f"文件 '{args.csv_file_path}' 中列 '{args.column_name}' 的平均值是: {average_value:.4f}") # 保留四位小数

if __name__ == "__main__":
    main()