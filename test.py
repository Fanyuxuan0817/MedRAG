from paddleocr import PPStructureV3

pipeline = PPStructureV3(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False
)

output = pipeline.predict(
    input="./pp_structure_v3_demo.png"
)

for res in output:
    res.print()
    res.save_to_json(save_path="./")
    res.save_to_markdown(save_path="./")