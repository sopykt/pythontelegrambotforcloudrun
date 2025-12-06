import pandas as pd
import imgkit
import os
import zipfile

# Burmese digits map
burmese_digits = str.maketrans("0123456789", "၀၁၂၃၄၅၆၇၈၉")

def to_burmese_number(n):
    return str(n).translate(burmese_digits)

def generate_image_from_html(html_content, output_path, wkhtmltopdf_path):
    """Helper to run imgkit with specific binary path"""
    config = imgkit.config(wkhtmltoimage=wkhtmltopdf_path)
    options = {
        'format': 'png',
        'encoding': "UTF-8",
        'enable-local-file-access': None,
        'quiet': ''
    }
    imgkit.from_string(html_content, output_path, config=config, options=options)

def build_custom_table(df):
    df = df.reset_index(drop=True)
    result = pd.DataFrame()

    result["စဉ်"] = [to_burmese_number(i+1) for i in range(len(df))]
    result["ကိုယ်ပိုင်အမှတ်"] = df['ကိုယ်ပိုင်အမှတ်']
    result["အဆင့်"] = df["အဆင့်"]

    pattern = r"ကြည်း|ရေ|လေ|အန်|N"
    result["လူနာအမျိုး အစား"] = df["ကိုယ်ပိုင်အမှတ်"].str.contains(pattern, case=False, na=False).map({True: "ရှိ", False: "ခြား"})

    result["အမည်"] = df["အမည်"]
    result["တော်စပ်ပုံ"] = df["တော်စပ်ပုံ"]
    result["မှီခို အမည်"] = df["မှီခိုအမည်"]
    result["အသက်"] = df["အသက်"]
    result["စစ်သက်"] = df["စစ်သက်"]
    result["တပ်"] = df["တပ်"]
    result["တိုင်း"] = df["တိုင်း"]
    result["ကွပ်ကဲမှု"] = df["ကွပ်ကဲမှု့"] 
    result["ဖြစ်စဉ်နေရာ"] = df["ဖြစ်စဥ်‌နေရာ"]
    result["ဖြစ်စဉ်ရက်စွဲ"] = df["ဖြစ်စဉ်ရက်စွဲ"]
    result["ရောဂါ(အဂ်လိပ်)"] = df["ရောဂါ(အဂ်လိပ်)"]
    result["ရောဂါ(မြန်မာ)"] = df["ရောဂါ(မြန်မာ)"]
    result["တက်ရောက် သည့်ဆေးရုံ"] = "မဆခွဲ ၂/၅"
    result["ဆေးရုံတက် ရက်စွဲ"] = df["ဆေးရုံတက်ရက်"]

    is_dead = df["ဆေးရုံဆင်းရက်"].str.contains(r"exp|die", case=False, na=False)
    result["ဆေးရုံဆင်း ရက်စွဲ"] = df["ဆေးရုံဆင်းရက်"].where(~is_dead, "")
    result["ဆေးရုံပြောင်း ရက်စွဲ"] = df["ဆေးရုံပြောင်းရက်"].where(~is_dead, "")
    result["သေဆုံး ရက်စွဲ"] = df["ဆေးရုံပြောင်းရက်"].where(is_dead, "")
    result["မှတ်ချက်"] = df["မှတ်ချက်"]

    return result.fillna('')

# --- MODULAR GENERATORS ---

def _gen_tatsin(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats=['e', 'p']):
    files = []
    # Filter for Tatsin
    cols_check = ['ဆေးရုံတက်ရက်', 'ဆေးရုံဆင်းရက်', 'ဆေးရုံပြောင်းရက်']
    df_bydate = df[df[cols_check].astype(str).apply(lambda row: row.str.contains(wanted_date_str, na=False)).any(axis=1)]

    if df_bydate.empty:
        return []

    table_df = build_custom_table(df_bydate)

    if 'e' in formats:
        excel_name = f"တက်ဆင်းပြောင်း_{wanted_date_str}.xlsx"
        table_df.to_excel(os.path.join(output_folder, excel_name), index=False)
        files.append(excel_name)

    if 'p' in formats:
        html = f"<html><head><meta charset='utf-8'>{font_css}</head><body><h3>ဆေးရုံ တက်/ဆင်း/ပြောင်း {wanted_date_str}</h3>{table_df.to_html(index=False, border=0)}</body></html>"
        img_name = f"တက်ဆင်းပြောင်း_{wanted_date_str}.png"
        generate_image_from_html(html, os.path.join(output_folder, img_name), wkhtmltopdf_path)
        files.append(img_name)
    
    return files

def _gen_sitchar(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats=['e', 'p']):
    files = []
    cols_na = ['ဆေးရုံဆင်းရက်','ဆေးရုံပြောင်းရက်']
    admitted_patients = df[df[cols_na].isna().all(axis=1)]

    if admitted_patients.empty:
        return []

    pattern = r'EAMI|EASPW|EAGSW'
    admitted_patients = admitted_patients.copy()
    admitted_patients['group'] = admitted_patients['ရောဂါ(အဂ်လိပ်)'].str.contains(pattern, case=False, na=False).map({True: 'စဆရ', False: 'အခြား'})

    pivot = pd.pivot_table(admitted_patients, index='group', columns='တပ်', values='ကိုယ်ပိုင်အမှတ်', aggfunc='count', fill_value=0)
    pivot.loc['ပေါင်း'] = pivot.sum()
    pivot['ပေါင်း'] = pivot.sum(axis=1)
    pivot.index.name = None
    pivot.columns.name = None

    if 'e' in formats:
        excel_name = f"စစ်ခြား_{wanted_date_str}.xlsx"
        pivot.to_excel(os.path.join(output_folder, excel_name))
        files.append(excel_name)

    if 'p' in formats:
        html = f"<html><head><meta charset='utf-8'>{font_css}</head><body><h3>စစ်ဆင်ရေးဒဏ်ရာနှင့် အခြားရောဂါ အခြေပြဇယား {wanted_date_str}</h3>{pivot.to_html(border=0)}</body></html>"
        img_name = f"စစ်ခြား_{wanted_date_str}.png"
        generate_image_from_html(html, os.path.join(output_folder, img_name), wkhtmltopdf_path)
        files.append(img_name)
    
    return files

def _gen_room(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats=['e', 'p']):
    files = []
    cols_na = ['ဆေးရုံဆင်းရက်','ဆေးရုံပြောင်းရက်']
    admitted_patients = df[df[cols_na].isna().all(axis=1)]

    if admitted_patients.empty or 'room' not in admitted_patients.columns:
        return []

    pivot_room = pd.pivot_table(admitted_patients, index='room', columns='တပ်', values='ကိုယ်ပိုင်အမှတ်', aggfunc='count', fill_value=0)
    pivot_room.loc['ပေါင်း'] = pivot_room.sum()
    pivot_room['ပေါင်း'] = pivot_room.sum(axis=1)
    pivot_room.index.name = None
    pivot_room.columns.name = None

    if 'e' in formats:
        excel_name = f"ဆေးရုံတက်နေရာ_{wanted_date_str}.xlsx"
        pivot_room.to_excel(os.path.join(output_folder, excel_name))
        files.append(excel_name)

    if 'p' in formats:
        html = f"<html><head><meta charset='utf-8'>{font_css}</head><body><h3>ဆေးရုံတက်နေရာ အခြေပြဇယား {wanted_date_str}</h3>{pivot_room.to_html(border=0)}</body></html>"
        img_name = f"ဆေးရုံတက်နေရာ_{wanted_date_str}.png"
        generate_image_from_html(html, os.path.join(output_folder, img_name), wkhtmltopdf_path)
        files.append(img_name)
    
    return files

# --- MAIN FUNCTIONS ---

def process_data(input_file_path, output_folder, wanted_date_str, font_path, wkhtmltopdf_path):
    """
    Original function for the 'Generate All' button. 
    It simply calls all 3 specific generators with defaults.
    """
    df = pd.read_excel(input_file_path)
    
    font_css = f"""
    <style>
        @font-face {{
          font-family: 'NotoSansMyanmar';
          src: url('file://{font_path}') format('truetype');
        }}
        body {{ font-family: 'NotoSansMyanmar', sans-serif; }}
        table {{ border-collapse: collapse; font-size: 15px; width: 100%; }}
        th, td {{ border: 1px solid #444; padding: 4px 8px; text-align: center; }}
        th {{ background: #f2f2f2; }}
    </style>
    """
    
    all_files = []
    all_files.extend(_gen_tatsin(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path))
    all_files.extend(_gen_sitchar(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path))
    all_files.extend(_gen_room(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path))
    
    return all_files

def process_specific_report(input_file_path, output_folder, wanted_date_str, font_path, wkhtmltopdf_path, report_type, formats):
    """
    New function for /gen commands.
    """
    df = pd.read_excel(input_file_path)
    
    font_css = f"""
    <style>
        @font-face {{
          font-family: 'NotoSansMyanmar';
          src: url('file://{font_path}') format('truetype');
        }}
        body {{ font-family: 'NotoSansMyanmar', sans-serif; }}
        table {{ border-collapse: collapse; font-size: 15px; width: 100%; }}
        th, td {{ border: 1px solid #444; padding: 4px 8px; text-align: center; }}
        th {{ background: #f2f2f2; }}
    </style>
    """
    
    if report_type == 'tatsin':
        return _gen_tatsin(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats)
    elif report_type == 'sitchar':
        return _gen_sitchar(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats)
    elif report_type == 'room':
        return _gen_room(df, output_folder, wanted_date_str, font_css, wkhtmltopdf_path, formats)
    
    return []
