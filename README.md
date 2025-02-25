# PyTorch Toolbox for Image Quality Assessment

An IQA toolbox with pure python and pytorch. Please refer to [Awesome-Image-Quality-Assessment](https://github.com/chaofengc/Awesome-Image-Quality-Assessment) for a comprehensive survey of IQA methods, as well as download links for IQA datasets. 

## :open_book: Introduction

This is a image quality assessment toolbox with **pure python and pytorch**. We provide the following features:

- :sparkles: **Comprehensive.** Support many mainstream full reference (FR) and no reference (NR) metrics
- :sparkles: **Accurate.** Results calibration of our implementation with official matlab scripts (if exist). 
- :sparkles: **Fast.** With GPU acceleration, most of our implementation is much faster than Matlab. 
- :sparkles: **Flexible.** Support training new DNN models with several public IQA datasets
- :sparkles: **Differentiable.** Most methods support pytorch backward
- :sparkles: **Convenient.** Quick inference and benchmark script

Below are details of supported methods and datasets in this project. 

<details open>
<summary>Supported methods and datasets:</summary>

<table>
<tr><td>

| FR Method                       | Backward           |
| ------------------------------- | ------------------ |
| PieAPP :hourglass_flowing_sand: |                    |
| LPIPS                           | :white_check_mark: |
| DISTS                           | :white_check_mark: |
| WaDIQaM                         | :white_check_mark: |
| CKDN<sup>[1](#fn1)</sup>        | :white_check_mark: |
| FSIM                            | :white_check_mark: |
| SSIM                            | :white_check_mark: |
| MS-SSIM                         | :white_check_mark: |
| CW-SSIM                         | :white_check_mark: |
| PSNR                            | :white_check_mark: |
| VIF                             | :white_check_mark: |
| GMSD                            | :white_check_mark: |
| NLPD                            | :white_check_mark: |
| VSI                             | :white_check_mark: |
| MAD                             | :white_check_mark: |

</td><td>

| NR Method                          | Backward           |
| ---------------------------------- | ------------------ |
| MUSIQ                              | :white_check_mark: |
| DBCNN                              | :white_check_mark: |
| PaQ-2-PiQ :hourglass_flowing_sand: |                    |
| HyperIQA                           | :white_check_mark: |
| NIMA                               | :white_check_mark: |
| WaDIQaM                            | :white_check_mark: |
| CNNIQA                             | :white_check_mark: |
| NRQM(Ma)<sup>[2](#fn2)</sup>       | :x:                |
| PI(Perceptual Index)               | :x:                |
| HOSA :hourglass_flowing_sand:      |                    |
| BRISQUE                            | :white_check_mark: |
| ILNIQE                             | :white_check_mark: |
| NIQE                               | :white_check_mark: |

</td><td>

| Dataset          | Type         |
| ---------------- | ------------ |
| FLIVE(PaQ-2-PiQ) | NR           |
| SPAQ             | NR/mobile    |
| AVA              | NR/Aesthetic |
| PIPAL            | FR           |
| BAPPS            | FR           |
| PieAPP           | FR           |
| KADID-10k        | FR           |
| KonIQ-10k(++)    | NR           |
| LIVEChallenge    | NR           |
| LIVEM            | FR           |
| LIVE             | FR           |
| TID2013          | FR           |
| TID2008          | FR           |
| CSIQ             | FR           |

</td></tr> 
</table>

<a name="fn1">[1]</a> This method use distorted image as reference. Please refer to the paper for details.   
<a name="fn2">[2]</a> Currently, only naive random forest regression is implemented and **does not** support backward and GPU. Nevertheless, with fast GPU feature calculation, our implementation is still **x2 faster** than Matlab (5s v.s. 10s with 512x384 input image)

</details>

---

### :triangular_flag_on_post: Updates/Changelog

- **March 5, 2022**. Add NRQM, PI, ILNIQE metrics. 
- **Feb 2, 2022**. Add MUSIQ inference code, and the converted official weights. See [Official codes](https://github.com/google-research/google-research/tree/master/musiq). 
- [**More**](docs/history_changelog.md)

---

### :hourglass_flowing_sand: TODO List

- :white_large_square: Benchmark with retrained models of DBCNN, NIMA, etc. 
- :white_large_square: Add pretrained models on different datasets.

---

## :zap: Quick Start

### Dependencies and Installation
- Ubuntu >= 18.04
- Python >= 3.8
- Pytorch >= 1.8.1
- CUDA 10.1 (if use GPU)
- Other required packages in `requirements.txt`
```
# Install with pip
pip install pyiqa

# Install latest github version
pip install git+https://github.com/chaofengc/IQA-PyTorch.git

# Install with git clone 
git clone https://github.com/chaofengc/IQA-PyTorch.git
cd IQA-PyTorch
pip install -r requirements.txt
python setup.py develop 
```

### Quick Inference

#### Test script 

Example test script with input directory and reference directory. Single image is also supported for `-i` and `-r` options. 
```
# example for FR metric with dirs 
python inference_iqa.py -n LPIPS[or lpips] -i ./ResultsCalibra/dist_dir -r ./ResultsCalibra/ref_dir 

# example for NR metric with single image
python inference_iqa.py -n brisque -i ./ResultsCalibra/dist_dir/I03.bmp 
```

#### Used as functions in your project
```
import pyiqa 

# list all available metrics
print(pyiqa.list_models())

# create metric with default setting
iqa_metric = pyiqa.create_metric('lpips').to(device)

# create metric with custom setting
iqa_metric = pyiqa.create_metric('psnr', test_y_channel=True).to(device)

# example for iqa score inference
# img_tensor_x/y: (N, 3, H, W), RGB, 0 ~ 1
score_fr = iqa_metric(img_tensor_x, img_tensor_y)
score_nr = iqa_metric(img_tensor_x)
```

Metrics which support backward can be used for optimization, such as image enhancement.

## :hammer_and_wrench: Train 

### Dataset Preparation

- You only need to unzip downloaded datasets from official website without any extra operation. And then make soft links of these dataset folder under `datasets/` folder. Download links are provided in [Awesome-Image-Quality-Assessment](https://github.com/chaofengc/Awesome-Image-Quality-Assessment).  
- We provide common interface to load these datasets with the prepared meta information files and train/val/test split files, which can be downloaded from [download_link](https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/data_info_files.tgz) and extract them to `datasets/` folder. 

You may also use the following commands:

```
mkdir datasets && cd datasets 

# make soft links of your dataset
ln -sf your/dataset/path datasetname

# download meta info files and train split files
wget https://github.com/chaofengc/IQA-PyTorch/releases/download/v0.1-weights/data_info_files.tgz
tar -xvf data_info_files.tgz 
``` 

Examples to specific dataset options can be found in `./options/default_dataset_opt.yml`. Details of the dataloader inferface and meta information files can be found in [Dataset Preparation](docs/Dataset_Preparation.md) 

### Example Train Script 

Example to train DBCNN on LIVEChallenge dataset
```
# train for single experiment
python pyiqa/train.py -opt options/train/train_DBCNN.yml 

# train N splits for small datasets
python pyiqa/train_nsplits.py -opt options/train/train_DBCNN.yml 
```

## :1st_place_medal: Benchmark Performances and Model Zoo

### Results Calibration

Please refer to the [results calibration](./ResultsCalibra/ResultsCalibra.md) to verify the correctness of the python implementations compared with official scripts in matlab or python.

### Performances of classical metrics 

Here is an example script to get performance benchmark on different datasets:
```
# NOTE: this script will test ALL specified metrics on ALL specified datasets
# Test default metrics on default datasets
python benchmark_results.py -m psnr ssim -d csiq tid2013 tid2008 

# Test with your own options
python benchmark_results.py -m psnr --data_opt options/example_benchmark_data_opts.yml

python benchmark_results.py --metric_opt options/example_benchmark_metric_opts.yml tid2013 tid2008

python benchmark_results.py --metric_opt options/example_benchmark_metric_opts.yml --data_opt options/example_benchmark_data_opts.yml
```
Please refer to [benchmark results](tests/benchmark_results.csv) for benchmark results of traditional metrics.

### Performances of deep learning models

#### Small datasets, n-splits validation 

| Methods | CSIQ | TID2008 | TID2013 | LIVE | LIVEM | LIVEC |
| ------- | ---- | ------- | ------- | ---- | ----- | ----- |
| DBCNN   |      |         |         |      |       |       |

#### Large dataset performance

| Methods | Dataset | Kon10k | LIVEC | SPAQ | AVA | Link(pth) |
| ------- | ------- | ------ | ----- | ---- | --- | --------- |

## :beers: Contribution

Any contributions to this repository are greatly appreciated. Please follow the [contribution instructions](docs/Instruction.md) for contribution guidance.  

## :receipt: License

This work is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License</a>.

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" /></a>

<!-- ## :bookmark_tabs: Citation

```
TODO -->
<!-- ``` -->

## :heart: Acknowledgement

The code architecture is borrowed from [BasicSR](https://github.com/xinntao/BasicSR). Several implementations are taken from 

- [IQA-optimization](https://github.com/dingkeyan93/IQA-optimization)  
- [Image-Quality-Assessment-Toolbox](https://github.com/RyanXingQL/Image-Quality-Assessment-Toolbox) 
- [piq](https://github.com/photosynthesis-team/piq)
- [piqa](https://github.com/francois-rozet/piqa)

We also thanks the following public repositories: 
- [MUSIQ]() 
- [DBCNN](https://github.com/zwx8981/DBCNN-PyTorch) 
- [NIMA](https://github.com/kentsyx/Neural-IMage-Assessment)
- [HyperIQA](https://github.com/SSL92/hyperIQA)
- [CNNIQA](https://github.com/lidq92/CNNIQA)
- [WaDIQaM](https://github.com/lidq92/WaDIQaM)

## :e-mail: Contact

If you have any questions, please email `chaofenghust@gmail.com`
