import pandas as pd
import os
from ai_engine import AIEngine

def check_and_train():
    data_path = "training_data.csv"
    if not os.path.exists(data_path):
        print(f"❌ Error: {data_path} not found")
        return

    df = pd.read_csv(data_path)
    print(f"📊 Всего записей: {len(df)}")
    if 'target' in df.columns:
        print("📈 Баланс классов (target):")
        print(df['target'].value_counts())
    else:
        print("❌ Error: 'target' column missing in CSV")
        return

    if len(df) < 50:
        print("⚠️ Предупреждение: Мало данных для обучения. Рекомендуется >100.")
    
    print("\n🚀 Запуск обучения...")
    ai = AIEngine()
    result = ai.train_model(data_path)
    print("✅ Результат обучения:", result)

    if ai.model:
        print("\n📊 Важность признаков (Feature Importance):")
        importances = ai.model.feature_importances_
        feat_imp = sorted(zip(ai.features, importances), key=lambda x: x[1], reverse=True)
        for feat, imp in feat_imp:
            print(f"  - {feat:15}: {imp:.4f}")

if __name__ == "__main__":
    check_and_train()
