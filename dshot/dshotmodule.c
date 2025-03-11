#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>
#include <stdlib.h>

extern void motorImplementationInitialize(int motorPins[], int motorMax);
extern void motorImplementationFinalize(int motorPins[], int motorMax);
extern void motorImplementationSendThrottles(int motorPins[], int motorMax, double motorThrottle[]);
extern void motorImplementationSet3dModeAndSpinDirection(int motorPins[], int motorMax, int mode3dFlag, int reverseDirectionFlag);

static PyObject* dshot_initialize(PyObject* self, PyObject* args) {
    PyObject* pin_list;
    
    if (!PyArg_ParseTuple(args, "O", &pin_list)) {
        return NULL;
    }
    
    if (!PyList_Check(pin_list)) {
        PyErr_SetString(PyExc_TypeError, "Argument must be a list of GPIO pins");
        return NULL;
    }
    
    int motor_count = PyList_Size(pin_list);
    if (motor_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "GPIO pin list cannot be empty");
        return NULL;
    }
    
    int* motor_pins = (int*)malloc(motor_count * sizeof(int));
    if (!motor_pins) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory");
        return NULL;
    }
    
    for (int i = 0; i < motor_count; i++) {
        PyObject* item = PyList_GetItem(pin_list, i);
        if (!PyLong_Check(item)) {
            free(motor_pins);
            PyErr_SetString(PyExc_TypeError, "GPIO pins must be integers");
            return NULL;
        }
        
        int pin = PyLong_AsLong(item);
        if (pin < 8 || pin > 25) {
            free(motor_pins);
            PyErr_SetString(PyExc_ValueError, "GPIO pins must be between 8 and 25");
            return NULL;
        }
        
        motor_pins[i] = pin;
    }
    
    motorImplementationInitialize(motor_pins, motor_count);
    free(motor_pins);
    
    Py_RETURN_NONE;
}

static PyObject* dshot_finalize(PyObject* self, PyObject* args) {
    PyObject* pin_list;
    
    if (!PyArg_ParseTuple(args, "O", &pin_list)) {
        return NULL;
    }
    
    if (!PyList_Check(pin_list)) {
        PyErr_SetString(PyExc_TypeError, "Argument must be a list of GPIO pins");
        return NULL;
    }
    
    int motor_count = PyList_Size(pin_list);
    if (motor_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "GPIO pin list cannot be empty");
        return NULL;
    }
    
    int* motor_pins = (int*)malloc(motor_count * sizeof(int));
    if (!motor_pins) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory");
        return NULL;
    }
    
    for (int i = 0; i < motor_count; i++) {
        PyObject* item = PyList_GetItem(pin_list, i);
        if (!PyLong_Check(item)) {
            free(motor_pins);
            PyErr_SetString(PyExc_TypeError, "GPIO pins must be integers");
            return NULL;
        }
        
        motor_pins[i] = PyLong_AsLong(item);
    }
    
    motorImplementationFinalize(motor_pins, motor_count);
    free(motor_pins);
    
    Py_RETURN_NONE;
}

static PyObject* dshot_send_throttles(PyObject* self, PyObject* args) {
    PyObject* pin_list;
    PyObject* throttle_list;
    
    if (!PyArg_ParseTuple(args, "OO", &pin_list, &throttle_list)) {
        return NULL;
    }
    
    if (!PyList_Check(pin_list) || !PyList_Check(throttle_list)) {
        PyErr_SetString(PyExc_TypeError, "Arguments must be lists");
        return NULL;
    }
    
    int motor_count = PyList_Size(pin_list);
    if (motor_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "GPIO pin list cannot be empty");
        return NULL;
    }
    
    if (PyList_Size(throttle_list) != motor_count) {
        PyErr_SetString(PyExc_ValueError, "Throttle list must have same length as pin list");
        return NULL;
    }
    
    int* motor_pins = (int*)malloc(motor_count * sizeof(int));
    double* throttles = (double*)malloc(motor_count * sizeof(double));
    
    if (!motor_pins || !throttles) {
        free(motor_pins);
        free(throttles);
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory");
        return NULL;
    }
    
    for (int i = 0; i < motor_count; i++) {
        PyObject* pin_item = PyList_GetItem(pin_list, i);
        PyObject* throttle_item = PyList_GetItem(throttle_list, i);
        
        if (!PyLong_Check(pin_item) || !PyFloat_Check(throttle_item)) {
            free(motor_pins);
            free(throttles);
            PyErr_SetString(PyExc_TypeError, "Pins must be integers, throttles must be floats");
            return NULL;
        }
        
        motor_pins[i] = PyLong_AsLong(pin_item);
        throttles[i] = PyFloat_AsDouble(throttle_item);
        
        if (throttles[i] < 0.0 || throttles[i] > 1.0) {
            free(motor_pins);
            free(throttles);
            PyErr_SetString(PyExc_ValueError, "Throttle values must be between 0.0 and 1.0");
            return NULL;
        }
    }
    
    motorImplementationSendThrottles(motor_pins, motor_count, throttles);
    
    free(motor_pins);
    free(throttles);
    
    Py_RETURN_NONE;
}

static PyObject* dshot_set_3d_mode(PyObject* self, PyObject* args) {
    PyObject* pin_list;
    int enable_3d;
    int reverse_direction;
    
    if (!PyArg_ParseTuple(args, "Oii", &pin_list, &enable_3d, &reverse_direction)) {
        return NULL;
    }
    
    if (!PyList_Check(pin_list)) {
        PyErr_SetString(PyExc_TypeError, "First argument must be a list of GPIO pins");
        return NULL;
    }
    
    int motor_count = PyList_Size(pin_list);
    if (motor_count <= 0) {
        PyErr_SetString(PyExc_ValueError, "GPIO pin list cannot be empty");
        return NULL;
    }
    
    int* motor_pins = (int*)malloc(motor_count * sizeof(int));
    if (!motor_pins) {
        PyErr_SetString(PyExc_MemoryError, "Failed to allocate memory");
        return NULL;
    }
    
    for (int i = 0; i < motor_count; i++) {
        PyObject* item = PyList_GetItem(pin_list, i);
        if (!PyLong_Check(item)) {
            free(motor_pins);
            PyErr_SetString(PyExc_TypeError, "GPIO pins must be integers");
            return NULL;
        }
        
        motor_pins[i] = PyLong_AsLong(item);
    }
    
    motorImplementationSet3dModeAndSpinDirection(motor_pins, motor_count, enable_3d, reverse_direction);
    free(motor_pins);
    
    Py_RETURN_NONE;
}

static PyMethodDef DshotMethods[] = {
    {"initialize", dshot_initialize, METH_VARARGS, "Initialize DSHOT for specific GPIO pins"},
    {"finalize", dshot_finalize, METH_VARARGS, "Finalize DSHOT and clean up resources"},
    {"send_throttles", dshot_send_throttles, METH_VARARGS, "Send throttle values to ESCs"},
    {"set_3d_mode", dshot_set_3d_mode, METH_VARARGS, "Set 3D mode and spin direction"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef dshotmodule = {
    PyModuleDef_HEAD_INIT,
    "dshot",
    "DSHOT protocol implementation for Raspberry Pi using SMI and DMA",
    -1,
    DshotMethods
};

PyMODINIT_FUNC PyInit_dshot(void) {
    return PyModule_Create(&dshotmodule);
}
